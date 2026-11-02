import Brand from "./Brand.jsx";
import ThemeToggle from "./ThemeToggle.jsx";
import { CAMPUS } from "../labels.js";

export default function GenderGate({ campus, onBack, onSelect }) {
  return (
    <div className="gate">
      <header className="gate__top"><Brand/><ThemeToggle compact/></header>
      <div className="gate__inner">
        <p className="gate__eyebrow">СОСЕДИ · ДИСК И ОБЛАКО</p>

        <h1 className="gate__title">
          С кем ты будешь <span className="accent">жить?</span>
        </h1>
        <p className="gate__subtitle">
          Парни живут с парнями, девушки — с девушками.
          <br />
          Выбери, кого показывать в ленте.
        </p>

        <p className="gate__campus">Кампус-отель «{CAMPUS[campus]}»</p>
        <div className="gate__options">
          <button
            className="gate__option"
            onClick={() => onSelect("male")}
          >
            <img className="gate__drawing" src="/identity/person.svg" alt="" width="56" height="56"/>
            <span className="gate__label">Я парень</span>
            <span className="gate__hint">Показать парней</span>
          </button>

          <button
            className="gate__option"
            onClick={() => onSelect("female")}
          >
            <img className="gate__drawing" src="/identity/person.svg" alt="" width="56" height="56"/>
            <span className="gate__label">Я девушка</span>
            <span className="gate__hint">Показать девушек</span>
          </button>
        </div>
        <button className="gate__back" type="button" onClick={onBack}>← Вернуться назад</button>
      </div>
    </div>
  );
}
