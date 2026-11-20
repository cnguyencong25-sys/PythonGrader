(() => {
  const canvas = document.getElementById("loginMascot");
  const stage = canvas && canvas.closest(".login-mascot-stage");
  const email = document.getElementById("email");
  const passwordFields = Array.from(
    document.querySelectorAll("[data-private-password]"),
  );
  const passwordVisibilityToggles = Array.from(
    document.querySelectorAll("[data-password-visibility-toggle]"),
  ).map(toggle => ({
    toggle,
    field: document.getElementById(toggle.getAttribute("aria-controls")),
  }));
  let resolveMascotReady;
  window.loginMascotReady = new Promise(resolve => {
    resolveMascotReady = resolve;
  });
  const settleMascotReady = ready => {
    if (!resolveMascotReady) return;
    window.clearTimeout(mascotReadyTimeout);
    resolveMascotReady(ready);
    resolveMascotReady = null;
  };
  const mascotReadyTimeout = window.setTimeout(
    () => settleMascotReady(false),
    3000,
  );
  if (!canvas || !stage || !email || !passwordFields.length || !passwordVisibilityToggles.length) {
    settleMascotReady(false);
    return;
  }

  if (passwordVisibilityToggles.some(({ field }) => !field || !passwordFields.includes(field))) {
    console.error("Nút hiện mật khẩu không liên kết với ô mật khẩu tương ứng.");
    settleMascotReady(false);
    return;
  }

  if (!window.rive || !window.rive.Rive) {
    console.error("Rive runtime chưa tải được; mascot đăng nhập không khả dụng.");
    stage.classList.add("is-unavailable");
    settleMascotReady(false);
    return;
  }

  let player;
  let lookOnEmail;
  let followOnEmail;
  let lookOnPassword;
  let peekOnPassword;
  let triggerSuccess;
  let triggerFail;
  let emailFocused = document.activeElement === email;
  let passwordFocused = passwordFields.some(field => field === document.activeElement);
  let mouseActive = false;
  let passwordVisible = passwordFields.some(field => field.type === "text");
  let loginResultPlayback = Promise.resolve();

  const setInput = (input, value) => {
    if (input) input.value = value;
  };

  const updateEmailLook = () => {
    setInput(followOnEmail, Math.min(email.value.length * 1.5, 100));
  };

  const updateGazeFocus = () => {
    setInput(lookOnEmail, emailFocused || mouseActive);
  };

  const updatePasswordState = () => {
    passwordFocused = passwordFields.some(field => field === document.activeElement);
    passwordVisible = passwordFields.some(field => field.type === "text");
    setInput(lookOnPassword, passwordFocused);
    setInput(peekOnPassword, passwordVisible);
  };

  const updateMouseLook = event => {
    mouseActive = true;
    updateGazeFocus();
    const viewportWidth = document.documentElement.clientWidth || window.innerWidth;
    const normalizedX = Math.max(0, Math.min(1, event.clientX / viewportWidth));
    setInput(followOnEmail, normalizedX * 100);
  };

  const resetMouseLook = () => {
    mouseActive = false;
    updateGazeFocus();
    if (emailFocused) updateEmailLook();
    else setInput(followOnEmail, 0);
  };

  const enqueueLoginResult = success => {
    loginResultPlayback = loginResultPlayback.then(async () => {
      const ready = await window.loginMascotReady;
      if (!ready) return;
      const trigger = success ? triggerSuccess : triggerFail;
      if (!trigger) return;
      trigger.fire();
      await new Promise(resolve => window.setTimeout(resolve, success ? 1000 : 700));
    });
    return loginResultPlayback;
  };

  try {
    player = new window.rive.Rive({
      src: "/static/animation/auth_teddy.riv",
      canvas,
      autoplay: true,
      stateMachines: "Login Machine",
      onLoad: () => {
        player.resizeDrawingSurfaceToCanvas();
        const inputs = player.stateMachineInputs("Login Machine");
        const getInput = name => inputs.find(input => input.name === name);

        lookOnEmail = getInput("isFocus");
        followOnEmail = getInput("numLook");
        lookOnPassword = getInput("isPrivateField");
        peekOnPassword = getInput("isPrivateFieldShow");
        triggerSuccess = getInput("successTrigger");
        triggerFail = getInput("failTrigger");

        updateGazeFocus();
        updatePasswordState();
        updateEmailLook();
        settleMascotReady(true);

        const resizeObserver = new ResizeObserver(() => {
          player.resizeDrawingSurfaceToCanvas();
        });
        resizeObserver.observe(canvas);
      },
      onLoadError: error => {
        console.error("Không thể tải animation mascot đăng nhập.", error);
        stage.classList.add("is-unavailable");
        settleMascotReady(false);
      },
    });
  } catch (error) {
    console.error("Không thể khởi tạo animation mascot đăng nhập.", error);
    stage.classList.add("is-unavailable");
    settleMascotReady(false);
  }

  email.addEventListener("focus", () => {
    emailFocused = true;
    updateGazeFocus();
  });
  email.addEventListener("blur", () => {
    emailFocused = false;
    updateGazeFocus();
  });
  email.addEventListener("input", updateEmailLook);
  passwordFields.forEach(field => {
    field.addEventListener("focus", updatePasswordState);
    field.addEventListener("blur", updatePasswordState);
  });

  passwordVisibilityToggles.forEach(({ toggle, field }) => {
    const eyeIcon = toggle.querySelector(".password-eye-icon");
    const eyeOffIcon = toggle.querySelector(".password-eye-off-icon");

    toggle.addEventListener("mousedown", event => {
      event.preventDefault();
    });
    toggle.addEventListener("click", () => {
      const visible = field.type !== "text";
      field.type = visible ? "text" : "password";
      toggle.setAttribute("aria-pressed", String(visible));
      toggle.setAttribute("aria-label", visible ? "Ẩn mật khẩu" : "Hiện mật khẩu");
      if (eyeIcon) eyeIcon.toggleAttribute("hidden", visible);
      if (eyeOffIcon) eyeOffIcon.toggleAttribute("hidden", !visible);
      field.focus({ preventScroll: true });
      updatePasswordState();
    });
  });

  document.addEventListener("mousemove", updateMouseLook, { passive: true });
  document.documentElement.addEventListener("mouseleave", resetMouseLook);
  window.addEventListener("blur", resetMouseLook);

  window.addEventListener("python-grader:login-result", event => {
    const playback = enqueueLoginResult(Boolean(event.detail && event.detail.success));
    if (event.detail && typeof event.detail.waitUntil === "function") {
      event.detail.waitUntil(playback);
    }
  });
})();
