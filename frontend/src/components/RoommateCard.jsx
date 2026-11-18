import { useId, useRef, useState } from "react";
import { profilePhoto, telegramLink } from "../links.mjs";
import { SLEEP, SMOKING, TRACK } from "../labels.js";
import { useDialogFocus } from "../useDialogFocus.js";
import { useModalLock } from "../useModalLock.js";
import ProfileSpecs from "./ProfileSpecs.jsx";

function MatchBadge({ match }) {
  if (!match) return null;
  return match.percent === 100
    ? <span className="card__ideal"><span aria-hidden="true">✓ </span>Совпадают привычки</span>
    : <span className="card__match">{match.percent}% совпадения</span>;
}

function RoomStatus({ room }) {
  return <span className="card__recruiting">
    В комнате · свободно {room.spots_left} {room.spots_left === 1 ? "место" : "места"}
  </span>;
}

function ProfileDetails({ profile, match, myProfile, capacities, invite, busy, onInvite, onOpenRoom, canModerate, onAdminDelete, actionError, onClose }) {
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const dialogRef = useRef(null);
  const headingId = useId();
  useModalLock();
  useDialogFocus(dialogRef, onClose, deleting);
  const contact = telegramLink(profile.telegram);
  const canInvite = myProfile && myProfile.id !== profile.id
    && myProfile.gender === profile.gender && myProfile.campus === profile.campus
    && !myProfile.group_id && !profile.group_id && !invite;
  const wanted = profile.room_capacities.filter(size => capacities.includes(size));
  const inviteSizes = wanted.length ? wanted : capacities;
  const openRoom = profile.open_room;

  return (
    <div className="modal__overlay roommate-dialog" onClick={event => {
      if (event.target === event.currentTarget && !deleting) onClose();
    }}>
      <div className="modal" ref={dialogRef} role="dialog" aria-modal="true" aria-labelledby={headingId} tabIndex={-1}>
        <div className="modal__head">
          <h2 id={headingId}>{profile.name}</h2>
          <button type="button" className="modal__close" aria-label="Закрыть анкету" onClick={onClose} disabled={deleting}>×</button>
        </div>
        <div className="modal__form roommate-dialog__content">
          {TRACK[profile.track] && <p className="card__faculty">{TRACK[profile.track]}</p>}
          {openRoom && <RoomStatus room={openRoom} />}
          {profile.bio && <p className="card__bio">{profile.bio}</p>}
          {match && (
            <div className="roommate-dialog__match">
              <strong>Совпало {match.matched} из {match.fields.size}</strong>
              <p>Сравниваем привычки, указанные в обеих анкетах.</p>
            </div>
          )}
          <ProfileSpecs profile={profile} match={match} />
          {openRoom && <button type="button" className="card__room-action" onClick={() => {
            onClose();
            onOpenRoom(profile.group_id);
          }}>Посмотреть комнату</button>}
          {canInvite && (
            <div className="card__invite">
              <span className="card__invite-label">Позвать жить вместе:</span>
              <div className="card__invite-btns">
                {inviteSizes.map(size => (
                  <button type="button" key={size} className="card__invite-btn"
                    onClick={() => onInvite(profile.id, size)} disabled={busy}>на {size}</button>
                ))}
              </div>
            </div>
          )}
          {actionError && <p className="modal__error" role="alert">{actionError}</p>}
          {invite && <p className="card__invite-sent">Приглашение в комнату на {invite.capacity} отправлено</p>}
          {contact
            ? <a className="card__tg" href={contact} target="_blank" rel="noopener noreferrer">Написать в Telegram ↗</a>
            : <p className="card__faculty">Контакт в Telegram не указан</p>}
          {canModerate && (
            <div className="card__mod">
              {confirmDelete ? (
                <>
                  <span className="card__mod-ask">Удалить анкету?</span>
                  <button type="button" className="card__mod-keep" onClick={() => setConfirmDelete(false)} disabled={deleting}>Оставить</button>
                  <button type="button" className="card__mod-del" disabled={busy || deleting} onClick={async () => {
                    setDeleting(true);
                    const deleted = await onAdminDelete(profile.id);
                    if (deleted) onClose();
                    else setDeleting(false);
                  }}>Удалить</button>
                </>
              ) : (
                <button type="button" className="card__mod-del" onClick={() => setConfirmDelete(true)} disabled={busy}>Удалить анкету</button>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

export default function RoommateCard({ profile, match, highlight, onOpenRoom, ...details }) {
  const [expanded, setExpanded] = useState(false);
  const copyId = useId();
  const photo = profilePhoto(profile.photo_url);
  const room = profile.open_room;
  const sizes = room ? [room.capacity] : profile.room_capacities;
  const summary = [sizes.length ? `На ${sizes.join(" или ")}` : null, SLEEP[profile.sleep_schedule], SMOKING[profile.smoking]]
    .filter(Boolean).join(" · ");
  const fullMatch = match?.percent === 100;

  return (
    <article id={`profile-${profile.id}`} className={`card roommate-card${highlight ? " card--highlight" : ""}${fullMatch ? " roommate-card--match" : ""}`}>
      <button type="button" className="roommate-card__preview" aria-haspopup="dialog" aria-label={`Открыть анкету: ${profile.name}`} aria-describedby={copyId} onClick={() => setExpanded(true)}>
        <span className="card__photo" aria-hidden="true">
          {photo
            ? <img src={photo} referrerPolicy="no-referrer" alt="" loading="lazy" decoding="async" width="96" height="96" />
            : <span className="card__placeholder">{profile.name.trim().charAt(0).toUpperCase()}</span>}
        </span>
        <span className="roommate-card__copy" id={copyId}>
          <span className="roommate-card__top">
            <span className="card__name">{profile.name}{profile.telegram_verified && <span className="card__verified" title="Подтверждено через Telegram">✓</span>}</span>
            <span className="roommate-card__chevron" aria-hidden="true">›</span>
          </span>
          {summary && <span className="roommate-card__summary">{summary}</span>}
          {room && <RoomStatus room={room} />}
          {profile.bio && <span className="card__bio">{profile.bio}</span>}
          <MatchBadge match={match} />
        </span>
      </button>
      {room && <button type="button" className="card__room-action" onClick={() => onOpenRoom(profile.group_id)}>Посмотреть комнату</button>}
      {expanded && <ProfileDetails {...details} profile={profile} match={match} onOpenRoom={onOpenRoom} onClose={() => setExpanded(false)} />}
    </article>
  );
}
