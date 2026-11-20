(() => {
  const snow = document.getElementById("loginSnow");
  if (!snow || window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;

  for (let index = 0; index < 36; index += 1) {
    const flake = document.createElement("span");
    flake.className = "login-snowflake";
    flake.style.setProperty("--snow-x", `${Math.random() * 100}%`);
    flake.style.setProperty("--snow-size", `${2 + Math.random() * 3}px`);
    flake.style.setProperty("--snow-opacity", `${0.3 + Math.random() * 0.55}`);
    flake.style.setProperty("--snow-duration", `${7 + Math.random() * 9}s`);
    flake.style.setProperty("--snow-delay", `${-Math.random() * 15}s`);
    flake.style.setProperty("--snow-drift", `${Math.round(Math.random() * 110 - 55)}px`);
    snow.appendChild(flake);
  }
})();
