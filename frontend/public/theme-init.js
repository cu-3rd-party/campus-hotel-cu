// Применяем тему до отрисовки, чтобы не было вспышки светлого экрана.
(function () {
  var theme;
  try {
    theme = localStorage.getItem("obshaga_theme");
  } catch (e) {
    // Даже без доступа к localStorage можно применить тему устройства.
  }
  if (theme !== "light" && theme !== "dark") {
    theme = window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
  }
  document.documentElement.setAttribute("data-theme", theme);
})();
