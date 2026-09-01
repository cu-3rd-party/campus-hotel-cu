from datetime import datetime
from html import escape
from typing import Optional, List
import logging

from fastapi import HTTPException, Header, Depends
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from backend import (
    models,
    config,
    campuses,
    schemas,
    telegram_auth,
    storage,
    notifier,
    join_flow,
    block_flow,
    admin_export,
)
from backend.database import get_db

log = logging.getLogger(__name__)

# Бытовые привычки, по которым считаем «идеального соседа». Курс и направление
# сюда не входят: они про учёбу, а не про то, каково будет жить вместе.
IDEAL_FIELDS = (
    "sleep_schedule",
    "smoking",
    "tidiness",
    "wakeup",
    "guests",
    "shower",
    "temperature",
    "noise",
    "alcohol",
    "snoring",
)

# «Без разницы» подходит к любому ответу — иначе человек, которому всё равно,
# не совпал бы ни с кем.
IDEAL_WILDCARD = "any"

# Пол в ленте: по нему сразу видно, откроется анкета или нет — лента у парней
# и девушек разная. Ключ «other» в анкетах не выбирается, но в колонке он
# возможен, поэтому запасной вариант тоже есть.
FEED_GENDER = {"male": "👨 Парень", "female": "👩 Девушка"}

TRACK_LABEL = {
    "dev": "Разработка",
    "business": "Бизнес",
    "design": "Дизайн",
    "ai": "ИИ",
    "undecided": "Не определился",
}


def _assert_is_me(actor: Optional[models.Profile], profile_id: int) -> None:
    """Запрещает действовать от чужого имени.

    actor is None — токен бота не настроен, проверка отключена.
    """
    if actor is None:
        return
    if actor.id != profile_id:
        raise HTTPException(
            status_code=403, detail="Можно действовать только от своего имени"
        )


def _is_admin(user: Optional[dict]) -> bool:
    if user is None:
        # Токена бота нет — подписи не проверяются, это только локальная
        # разработка. На проде токен есть всегда, иначе не работает вход.
        return not config.TELEGRAM_BOT_TOKEN
    return int(user["id"]) in config.ADMIN_TELEGRAM_IDS


def _assert_capacity_allowed(campus: str, capacity: int) -> None:
    """Размер комнаты должен существовать в этом кампус-отеле.

    В «Облаке» комнат на четверых нет, поэтому проверяем и здесь: фронт их
    не показывает, но запрос можно отправить и мимо него.
    """
    if not campuses.allows(campus, capacity):
        raise HTTPException(
            status_code=400,
            detail=(
                f"В кампус-отеле «{campuses.label(campus)}» комнаты только на "
                f"{campuses.capacities_text(campus)} человека"
            ),
        )


def _pack_lists(data: dict) -> None:
    """Готовит поля-списки анкеты к записи: проверяет и склеивает через запятую.

    Готовка и желаемые размеры комнаты приходят списками, а в колонках лежат
    строками ("self,together", "3,4"). Заодно сверяем размеры с кампус-отелем:
    в «Облаке» комнат на четверых нет, и фронт их не покажет — но запрос можно
    отправить и мимо него.
    """
    for capacity in data.get("room_capacities") or []:
        _assert_capacity_allowed(data["campus"], capacity)
    data["room_capacities"] = ",".join(str(c) for c in data["room_capacities"])
    data["cooking"] = ",".join(data["cooking"])


async def _telegram_profile(user: dict) -> schemas.TelegramProfileOut:
    """Из проверенных данных Telegram делаем превью для формы.

    Аватар скачиваем себе: ссылки t.me/i/userpic/... живут недолго.
    """
    photo_url = None
    remote = user.get("photo_url")
    if remote:
        raw = await telegram_auth.download_avatar(remote)
        if raw:
            try:
                photo_url = await run_in_threadpool(storage.save_image, raw)
            except storage.InvalidImage:
                photo_url = None

    name = " ".join(
        part for part in [user.get("first_name"), user.get("last_name")] if part
    ).strip()
    return schemas.TelegramProfileOut(
        telegram_id=int(user["id"]),
        telegram=user.get("username"),
        name=name or None,
        photo_url=photo_url,
    )


def _ideal_match(me: models.Profile, other: models.Profile) -> bool:
    """Совпали ли все бытовые параметры, которые я у себя указал.

    Незаполненные у меня поля не проверяем: я про них не высказался, значит и
    требовать от соседа нечего.
    """
    for field in IDEAL_FIELDS:
        mine = getattr(me, field)
        if not mine or mine == IDEAL_WILDCARD:
            continue
        theirs = getattr(other, field)
        if theirs != mine and theirs != IDEAL_WILDCARD:
            return False

    # Списки: достаточно пересечения. Пустой список — «не важно», подходит всё.
    for field in ("cooking", "room_capacities"):
        mine = {v for v in (getattr(me, field) or "").split(",") if v}
        theirs = {v for v in (getattr(other, field) or "").split(",") if v}
        if mine and theirs and not (mine & theirs):
            return False
    return True


def _feed_msgs(profile: models.Profile) -> List[dict]:
    """Анонс новой анкеты в общей ленте — теме супергруппы.

    Показываем имя, пол и кампус-отель: этого хватает, чтобы решить, открывать
    ли, а лента остаётся коротким списком «кто появился».
    """
    if not config.FEED_CHAT_ID:
        # Молчание тут — штатный режим (лента просто не настроена), но со
        # стороны оно неотличимо от поломки. Говорим об этом в лог один раз
        # на анкету, чтобы причину было видно сразу.
        log.info("Лента новых анкет выключена: не задан TELEGRAM_FEED_CHAT_ID")
        return []

    text = (
        "🆕 <b>Новая анкета</b>\n\n"
        f"👤 {escape(profile.name)}\n"
        f"{FEED_GENDER.get(profile.gender, '👤 Не указан')}\n"
        f"🏠 Кампус-отель «{campuses.label(profile.campus)}»\n\n"
        "<i>Лента разделена по полу: девушки видят только анкеты девушек, "
        "парни — только анкеты парней. Открыть чужую половину не получится.</i>"
    )
    return [
        {
            "chat_id": config.FEED_CHAT_ID,
            "message_thread_id": config.FEED_THREAD_ID,
            "text": text,
            "reply_markup": notifier.open_profile_keyboard(
                config.profile_link(profile.id)
            ),
        }
    ]


def _get_profile_or_404(db: Session, profile_id: int) -> models.Profile:
    profile = db.query(models.Profile).filter(models.Profile.id == profile_id).first()
    if not profile:
        raise HTTPException(status_code=404, detail="Анкета не найдена")
    return profile


def _get_group_or_404(db: Session, group_id: int) -> models.Group:
    group = db.query(models.Group).filter(models.Group.id == group_id).first()
    if not group:
        raise HTTPException(status_code=404, detail="Комната не найдена")
    return group


def _get_request_or_404(db: Session, request_id: int) -> models.JoinRequest:
    req = (
        db.query(models.JoinRequest).filter(models.JoinRequest.id == request_id).first()
    )
    if not req:
        raise HTTPException(status_code=404, detail="Заявка не найдена")
    return req


def _h(value: Optional[str]) -> str:
    """Готовит имя или ник к вставке в сообщение бота.

    Сообщения размечены HTML, а имя человек вводит сам. Без экранирования
    «Аня <3» либо теряет кусок текста, либо Telegram отказывается принимать
    сообщение целиком — и уведомление не доходит вообще ни до кого.

    Экранировать нужно ровно один раз, поэтому применяем в месте сборки
    текста: то, что уходит боту в JSON (см. /api/bot/*), остаётся сырым — там
    свой HTML собирает уже сам бот.
    """
    return escape(value or "")


def _who(profile: models.Profile) -> str:
    """Имя с направлением. Сырое: годится и для сообщения (через _h), и для JSON."""
    label = TRACK_LABEL.get(profile.track)
    return f"{profile.name} · {label}" if label else profile.name


def _msg(chat_id: Optional[int], text: str, reply_markup: Optional[dict] = None):
    """Один пункт для фоновой рассылки; без chat_id (не нажали /start) — пропуск."""
    return {"chat_id": chat_id, "text": text, "reply_markup": reply_markup}


def _request_msgs(req: models.JoinRequest) -> List[dict]:
    """Заявка ушла — зовём подтвердить всех, кто в комнате."""
    who = _h(_who(req.profile))
    needed = join_flow.votes_needed(req)
    msgs = []
    for member in req.group.members:
        if member.telegram_chat_id:
            msgs.append(
                _msg(
                    member.telegram_chat_id,
                    f"🔔 <b>{who}</b> просится к вам в комнату на {req.group.capacity}.\n"
                    f"@{_h(req.profile.telegram)}\n\n"
                    f"Нужно согласие всех участников ({needed}).",
                    notifier.vote_keyboard(req.id),
                )
            )
    return msgs


def _decision_msgs(req: models.JoinRequest, status: str) -> List[dict]:
    """Сообщаем автору заявки итог (приняли / отклонили / комната распалась)."""
    profile = req.profile
    if not profile.telegram_chat_id:
        return []
    if status == join_flow.APPROVED:
        mates = ", ".join(_h(m.name) for m in req.group.members if m.id != profile.id)
        return [
            _msg(
                profile.telegram_chat_id,
                f"🎉 Тебя приняли в комнату на {req.group.capacity}!\n"
                f"Соседи: {mates or '—'}\n\n{config.SITE_URL}",
            )
        ]
    if status == join_flow.REJECTED:
        return [
            _msg(
                profile.telegram_chat_id,
                "😔 Заявку в комнату отклонили. Не расстраивайся — "
                f"есть другие варианты: {config.SITE_URL}",
            )
        ]
    if status == join_flow.CANCELLED:
        return [_msg(profile.telegram_chat_id, "ℹ️ Заявка отменена: комната распалась.")]
    return []


def _group_msgs(
    group: models.Group, text: str, skip_id: Optional[int] = None
) -> List[dict]:
    """Одно и то же сообщение всем жильцам комнаты (кроме skip_id)."""
    return [
        _msg(m.telegram_chat_id, text)
        for m in group.members
        if m.telegram_chat_id and m.id != skip_id
    ]


def _close_group_blocks(db: Session, group: models.Group, note: str) -> List[dict]:
    """Отвязывает комнату от блока и гасит её заявки на объединение.

    Нужно, когда комната перестала подходить: распалась или изменила размер —
    в блоке должно быть ровно 6 человек, и половинка от него не имеет смысла.
    Сообщения не шлёт, а возвращает — их отправят в фоне после ответа клиенту.
    """
    msgs: List[dict] = []

    block = group.block if group.block_id else None
    if block is not None:
        for other in block.groups:
            if other.id != group.id:
                msgs += _group_msgs(
                    other,
                    f"🧩 Ваш блок распался: {note}.\n"
                    f"Можно объединиться с другой комнатой: {config.SITE_URL}",
                )
        block_flow.dissolve(db, block)

    for req in block_flow.cancel_for_group(db, group):
        other = req.to_group if req.from_group_id == group.id else req.from_group
        if other.id != group.id:
            msgs += _group_msgs(
                other,
                f"ℹ️ Предложение объединиться в блок отменено: {note}.",
            )
    return msgs


def _remove_from_group(
    db: Session,
    profile: models.Profile,
    note: str = "вышел(а) из вашей комнаты",
) -> List[dict]:
    """Выводит человека из комнаты и собирает уведомления оставшимся.

    Сообщения не шлёт, а возвращает: вызывающий отправит их в фоне уже после
    ответа клиенту. Опустевшую комнату удаляем — она никому не нужна.
    Одна дорога на все случаи выхода: вышел сам, удалил анкету, переехал.
    """
    group = profile.group if profile.group_id else None
    if group is None:
        return []

    left_name = _h(profile.name)
    profile.group_id = None
    db.flush()
    db.refresh(group)

    # Состав изменился — часть заявок могла «дозреть» без ушедшего.
    decided = []
    for req in list(group.requests):
        if req.status == join_flow.PENDING:
            new_status = join_flow.evaluate(db, req)
            if new_status != join_flow.PENDING:
                decided.append((req, new_status))

    msgs: List[dict] = []
    for member in group.members:
        if member.telegram_chat_id:
            msgs.append(
                _msg(
                    member.telegram_chat_id,
                    f"🚪 <b>{left_name}</b> {note}.\n"
                    f"Свободных мест стало больше: {config.SITE_URL}",
                )
            )
    for req, status in decided:
        msgs += _decision_msgs(req, status)

    if not group.members:
        # Комната распалась — вместе с ней уходит и её половина блока.
        msgs += _close_group_blocks(
            db, group, note=f"комната «на {group.capacity}» распалась"
        )
        db.delete(group)
    return msgs


def _close_pending(db: Session, profile: models.Profile) -> None:
    """Закрывает исходящие заявки и приглашения человека.

    Нужно, когда он выбывает: удалил анкету или переехал в другой кампус-отель —
    висящие «ждём ответа» после этого только путают остальных.
    """
    now = datetime.utcnow()
    db.query(models.JoinRequest).filter(
        models.JoinRequest.profile_id == profile.id,
        models.JoinRequest.status == join_flow.PENDING,
    ).update({"status": join_flow.CANCELLED, "decided_at": now})
    db.query(models.GroupInvite).filter(
        models.GroupInvite.status == "pending",
        (models.GroupInvite.from_profile_id == profile.id)
        | (models.GroupInvite.to_profile_id == profile.id),
    ).update({"status": "cancelled", "decided_at": now})


def _apply_vote(
    db: Session, req: models.JoinRequest, voter: models.Profile, approve: bool
) -> tuple[str, List[dict]]:
    """Записывает голос, пересчитывает статус и СОБИРАЕТ уведомления.

    Сами сообщения не шлёт — возвращает их, чтобы вызывающий отправил в фоне
    (BackgroundTasks) уже после ответа клиенту.
    """
    vote = (
        db.query(models.JoinRequestVote)
        .filter(
            models.JoinRequestVote.request_id == req.id,
            models.JoinRequestVote.member_id == voter.id,
        )
        .first()
    )
    if vote:
        vote.approve = approve  # передумал — перезаписываем
    else:
        db.add(
            models.JoinRequestVote(
                request_id=req.id, member_id=voter.id, approve=approve
            )
        )
    db.flush()
    db.refresh(req)

    status = join_flow.evaluate(db, req)
    also_rejected = []
    if status == join_flow.APPROVED:
        also_rejected = join_flow.close_obsolete(db, req.profile, req.group)
    db.commit()
    db.refresh(req)

    msgs: List[dict] = []
    if status != join_flow.PENDING:
        msgs += _decision_msgs(req, status)
    if status == join_flow.APPROVED:
        # Остальным в комнате — что состав пополнился.
        for member in req.group.members:
            if member.id != req.profile_id and member.telegram_chat_id:
                msgs.append(
                    _msg(
                        member.telegram_chat_id,
                        f"✅ <b>{_h(req.profile.name)}</b> теперь в вашей комнате.",
                    )
                )
        for other in also_rejected:
            msgs += _decision_msgs(other, join_flow.REJECTED)
    return status, msgs


def _request_out(req: models.JoinRequest) -> schemas.JoinRequestOut:
    votes = join_flow.active_votes(req)
    return schemas.JoinRequestOut(
        id=req.id,
        group_id=req.group_id,
        status=req.status,
        created_at=req.created_at,
        profile=schemas.GroupMemberOut.model_validate(req.profile),
        votes_needed=join_flow.votes_needed(req),
        votes_done=join_flow.votes_done(req),
        approved_by=[mid for mid, ok in votes.items() if ok],
    )


def _get_invite_or_404(db: Session, invite_id: int) -> models.GroupInvite:
    invite = (
        db.query(models.GroupInvite).filter(models.GroupInvite.id == invite_id).first()
    )
    if not invite:
        raise HTTPException(status_code=404, detail="Приглашение не найдено")
    return invite


def _assert_invite_still_valid(invite: models.GroupInvite) -> None:
    """Между приглашением и согласием могло многое измениться.

    Пока человек думал, любой из двоих мог вступить в другую комнату или
    переехать в другой кампус-отель — тогда комнату создавать уже нельзя.
    """
    if invite.from_profile.group_id or invite.to_profile.group_id:
        raise HTTPException(
            status_code=409, detail="Кто-то из вас уже успел вступить в комнату"
        )
    if invite.from_profile.campus != invite.to_profile.campus:
        raise HTTPException(
            status_code=409,
            detail="Кто-то из вас сменил кампус-отель — приглашение больше не действует",
        )
    _assert_capacity_allowed(invite.from_profile.campus, invite.capacity)


def _invite_msgs(invite: models.GroupInvite) -> List[dict]:
    """Зовём приглашённого подтвердить — кнопками прямо в Telegram."""
    target = invite.to_profile
    if not target.telegram_chat_id:
        return []
    return [
        _msg(
            target.telegram_chat_id,
            f"🤝 <b>{_h(_who(invite.from_profile))}</b> зовёт тебя жить вместе — "
            f"комната на {invite.capacity}.\n"
            f"@{_h(invite.from_profile.telegram)}\n\n"
            "Комната появится, только если ты согласишься.",
            notifier.invite_keyboard(invite.id),
        )
    ]


def _accept_invite(
    db: Session, invite: models.GroupInvite
) -> tuple[models.Group, List[dict]]:
    """Согласие: создаём комнату и заводим туда обоих."""
    author, target = invite.from_profile, invite.to_profile

    group = models.Group(
        capacity=invite.capacity, gender=author.gender, campus=author.campus
    )
    db.add(group)
    db.flush()  # нужен id до привязки участников
    author.group_id = group.id
    target.group_id = group.id

    invite.status = "accepted"
    invite.decided_at = datetime.utcnow()

    # Оба определились — их прочие заявки и приглашения теряют смысл.
    for profile in (author, target):
        db.query(models.JoinRequest).filter(
            models.JoinRequest.profile_id == profile.id,
            models.JoinRequest.status == join_flow.PENDING,
        ).update({"status": join_flow.CANCELLED, "decided_at": datetime.utcnow()})
        db.query(models.GroupInvite).filter(
            models.GroupInvite.id != invite.id,
            models.GroupInvite.status == "pending",
            (models.GroupInvite.from_profile_id == profile.id)
            | (models.GroupInvite.to_profile_id == profile.id),
        ).update({"status": "cancelled", "decided_at": datetime.utcnow()})

    msgs: List[dict] = []
    if author.telegram_chat_id:
        msgs.append(
            _msg(
                author.telegram_chat_id,
                f"🎉 <b>{_h(target.name)}</b> согласи(лся/лась) жить с тобой!\n"
                f"Комната на {invite.capacity} создана: {config.SITE_URL}",
            )
        )
    db.commit()
    db.refresh(group)
    return group, msgs


def _decline_invite(db: Session, invite: models.GroupInvite) -> List[dict]:
    invite.status = "declined"
    invite.decided_at = datetime.utcnow()
    author = invite.from_profile
    msgs: List[dict] = []
    if author.telegram_chat_id:
        msgs.append(
            _msg(
                author.telegram_chat_id,
                f"😔 <b>{_h(invite.to_profile.name)}</b> отказал(а)ся жить вместе. "
                f"Есть и другие варианты: {config.SITE_URL}",
            )
        )
    db.commit()
    return msgs


def _get_block_request_or_404(db: Session, request_id: int) -> models.BlockRequest:
    req = (
        db.query(models.BlockRequest)
        .filter(models.BlockRequest.id == request_id)
        .first()
    )
    if not req:
        raise HTTPException(status_code=404, detail="Заявка на блок не найдена")
    return req


def _my_group_or_403(
    db: Session, profile_id: int, actor: Optional[models.Profile]
) -> models.Group:
    """Комната того, кто действует. Блоками распоряжаются жильцы комнат."""
    _assert_is_me(actor, profile_id)
    profile = _get_profile_or_404(db, profile_id)
    if not profile.group_id:
        raise HTTPException(
            status_code=409,
            detail="Сначала соберите комнату — в блок объединяются комнатами",
        )
    return _get_group_or_404(db, profile.group_id)


def _block_request_out(req: models.BlockRequest) -> schemas.BlockRequestOut:
    votes = block_flow.active_votes(req)
    return schemas.BlockRequestOut(
        id=req.id,
        from_group_id=req.from_group_id,
        to_group_id=req.to_group_id,
        status=req.status,
        created_at=req.created_at,
        from_group=schemas.BlockRoomOut.model_validate(req.from_group),
        to_group=schemas.BlockRoomOut.model_validate(req.to_group),
        votes_needed=block_flow.votes_needed(req),
        votes_done=block_flow.votes_done(req),
        approved_by=[mid for mid, ok in votes.items() if ok],
    )


def _room_name(group: models.Group) -> str:
    """«Комната на 4 (Аня, Лена)» — чтобы понять, кого зовут, прямо в Telegram.

    Уходит только в текст сообщений, поэтому имена экранируем сразу здесь.
    """
    who = ", ".join(_h(m.name) for m in group.members)
    return f"комната на {group.capacity}" + (f" ({who})" if who else "")


def _apply_block_vote(
    db: Session, req: models.BlockRequest, voter: models.Profile, approve: bool
) -> tuple[str, List[dict]]:
    """Записывает голос, пересчитывает статус и СОБИРАЕТ уведомления.

    Как и у заявок в комнату, сообщения не шлёт: их отправят в фоне уже после
    ответа клиенту.
    """
    vote = (
        db.query(models.BlockRequestVote)
        .filter(
            models.BlockRequestVote.request_id == req.id,
            models.BlockRequestVote.member_id == voter.id,
        )
        .first()
    )
    if vote:
        vote.approve = approve  # передумал — перезаписываем
    else:
        db.add(
            models.BlockRequestVote(
                request_id=req.id, member_id=voter.id, approve=approve
            )
        )
    db.flush()
    db.refresh(req)

    status = block_flow.evaluate(db, req)
    also_closed: List[models.BlockRequest] = []
    if status == block_flow.APPROVED:
        also_closed = block_flow.close_obsolete(
            db, [req.from_group, req.to_group], keep=req
        )
    db.commit()
    db.refresh(req)

    msgs: List[dict] = []
    if status == block_flow.APPROVED:
        for group, other in (
            (req.from_group, req.to_group),
            (req.to_group, req.from_group),
        ):
            msgs += _group_msgs(
                group,
                f"🧩 Блок собран! Ваши соседи по блоку — <b>{_room_name(other)}</b>.\n"
                f"{config.SITE_URL}",
            )
        for other_req in also_closed:
            # Обе стороны несостоявшегося блока ждали ответа — говорим обеим.
            for group in (other_req.from_group, other_req.to_group):
                msgs += _group_msgs(
                    group,
                    "ℹ️ Предложение про блок отменено: комната успела "
                    "объединиться с другой.",
                )
    elif status == block_flow.REJECTED:
        msgs += _group_msgs(
            req.from_group,
            f"😔 <b>{_room_name(req.to_group)}</b> отказалась объединяться в блок. "
            f"Есть другие комнаты: {config.SITE_URL}",
        )
    return status, msgs


def _check_bot_secret(x_bot_secret: Optional[str] = Header(None)) -> None:
    if not config.BOT_SECRET:
        raise HTTPException(status_code=503, detail="BOT_SECRET не настроен")
    if x_bot_secret != config.BOT_SECRET:
        raise HTTPException(status_code=401, detail="Неверный секрет бота")


def _find_profile_by_telegram(
    db: Session, telegram_id: int, username: Optional[str]
) -> Optional[models.Profile]:
    """Ищем анкету: сначала по подтверждённому telegram_id, потом по нику."""
    profile = (
        db.query(models.Profile)
        .filter(models.Profile.telegram_id == telegram_id)
        .first()
    )
    if profile:
        return profile
    if username:
        return (
            db.query(models.Profile)
            .filter(models.Profile.telegram.ilike(username.lstrip("@")))
            .first()
        )
    return None


async def _fill_missing_usernames(db: Session, profiles: List[models.Profile]) -> None:
    """Дотягивает ники у тех, где остался только числовой ID.

    По одному ID человеку не напишешь, а выгрузка нужна как раз для связи.
    Найденные ники сохраняем — чтобы в следующий раз не ходить в Telegram.
    """
    unknown = [
        p.telegram_id
        for p in profiles
        if not p.telegram and (p.telegram_id or p.telegram_chat_id)
    ]
    if not unknown:
        return

    found = await telegram_auth.fetch_usernames([uid for uid in unknown if uid])
    if not found:
        return
    for profile in profiles:
        username = found.get(profile.telegram_id)
        if username and not profile.telegram:
            profile.telegram = username
    db.commit()


async def _build_export(
    db: Session, fmt: str, scope: str, campus: Optional[str]
) -> tuple[bytes, str, str]:
    """Собирает файл выгрузки: (содержимое, имя файла, MIME-тип).

    Общая дорога для обоих способов получить данные — скачиванием и файлом
    в Telegram: иначе они со временем разъедутся.
    """
    query = db.query(models.Profile)
    groups_query = db.query(models.Group)
    if campus:
        query = query.filter(models.Profile.campus == campus)
        groups_query = groups_query.filter(models.Group.campus == campus)

    profiles = query.order_by(models.Profile.created_at.desc()).all()
    groups = groups_query.all()

    await _fill_missing_usernames(db, profiles)

    stamp = datetime.now().strftime("%Y-%m-%d")
    part = "kratko" if scope == admin_export.SHORT else "polno"
    base = f"kampus-oteli-{part}-{stamp}"

    if fmt == "xlsx":
        return (
            admin_export.to_xlsx(profiles, groups, scope),
            f"{base}.xlsx",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
    if fmt == "csv":
        return (
            admin_export.to_csv_zip(profiles, groups, scope),
            f"{base}-csv.zip",
            "application/zip",
        )
    return (
        admin_export.to_json(profiles, groups, scope),
        f"{base}.json",
        "application/json; charset=utf-8",
    )


def optional_telegram_user(
    x_telegram_init_data: Optional[str] = Header(None),
) -> Optional[dict]:
    """Как telegram_user, но молча возвращает None вместо 401.

    Нужно там, где вход необязателен: например, чтобы решить, показывать ли
    кнопку админки, но не закрывать доступ к самой странице.
    """
    if not config.TELEGRAM_BOT_TOKEN or not x_telegram_init_data:
        return None
    try:
        return telegram_auth.verify_webapp_init_data(x_telegram_init_data)
    except telegram_auth.TelegramAuthError:
        return None


def telegram_user(
    x_telegram_init_data: Optional[str] = Header(None),
) -> Optional[dict]:
    """Проверенные данные Telegram из заголовка.

    Возвращает None, если проверка выключена (нет токена бота) — иначе
    локальная разработка и тесты стали бы невозможны.
    """
    if not config.TELEGRAM_BOT_TOKEN:
        return None
    if not x_telegram_init_data:
        raise HTTPException(status_code=401, detail="Нужен вход через Telegram")
    try:
        return telegram_auth.verify_webapp_init_data(x_telegram_init_data)
    except telegram_auth.TelegramAuthError as exc:
        raise HTTPException(status_code=401, detail=str(exc))


def current_profile(
    user: Optional[dict] = Depends(telegram_user),
    db: Session = Depends(get_db),
) -> Optional[models.Profile]:
    """Анкета того, кто сейчас делает запрос (None — проверка выключена)."""
    if user is None:
        return None
    return _find_profile_by_telegram(db, int(user["id"]), user.get("username"))


def require_admin(user: Optional[dict] = Depends(optional_telegram_user)) -> None:
    """Пускает только владельцев сервиса — выгрузка содержит чужие данные."""
    if not _is_admin(user):
        raise HTTPException(status_code=403, detail="Раздел только для админов")
