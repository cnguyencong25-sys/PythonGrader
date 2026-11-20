(() => {
  const canvases = document.querySelectorAll("[data-auth-mascot]");
  if (!canvases.length) return;

  if (!window.rive || !window.rive.Rive) {
    console.error("Rive runtime chưa tải được; mascot trang xác thực không khả dụng.");
    canvases.forEach(canvas => canvas.parentElement.classList.add("is-unavailable"));
    return;
  }

  canvases.forEach(canvas => {
    const stage = canvas.parentElement;
    let player;

    try {
      player = new window.rive.Rive({
        src: "/static/animation/auth_teddy.riv",
        canvas,
        autoplay: true,
        stateMachines: "Login Machine",
        onLoad: () => {
          player.resizeDrawingSurfaceToCanvas();
          const resizeObserver = new ResizeObserver(() => {
            player.resizeDrawingSurfaceToCanvas();
          });
          resizeObserver.observe(canvas);
        },
        onLoadError: error => {
          console.error("Không thể tải mascot trang xác thực.", error);
          stage.classList.add("is-unavailable");
        },
      });
    } catch (error) {
      console.error("Không thể khởi tạo mascot trang xác thực.", error);
      stage.classList.add("is-unavailable");
    }
  });
})();
