(() => {
  const transitionDuration = 280;
  const switchLinks = document.querySelectorAll(
    'a[href="/login"], a[href="/register"]',
  );

  switchLinks.forEach(link => {
    link.addEventListener("click", event => {
      if (
        event.defaultPrevented ||
        event.button !== 0 ||
        event.metaKey ||
        event.ctrlKey ||
        event.shiftKey ||
        event.altKey ||
        link.target === "_blank" ||
        link.pathname === window.location.pathname
      ) {
        return;
      }

      if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;

      event.preventDefault();
      document.body.classList.add("is-transitioning");
      window.setTimeout(() => {
        window.location.assign(link.href);
      }, transitionDuration);
    });
  });
})();
