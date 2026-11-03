      // Применяем тему до отрисовки, чтобы не было вспышки светлого экрана.
      (function () {
        try {
          var mode = localStorage.getItem("obshaga_theme") || "system";
          var dark =
            mode === "dark" ||
            (mode === "system" &&
              window.matchMedia("(prefers-color-scheme: dark)").matches);
          document.documentElement.setAttribute(
            "data-theme",
            dark ? "dark" : "light"
          );
        } catch (e) {}
      })();
