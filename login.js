const loginForm = document.querySelector(".login-form");
const passwordInput = document.querySelector("#staff-password");
const loginButton = loginForm.querySelector("button");
const loginStatus = document.querySelector(".login-status");

loginForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  loginButton.disabled = true;
  loginStatus.textContent = "";

  try {
    const response = await fetch("/api/admin/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ password: passwordInput.value }),
    });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.error || "Не удалось войти.");
    window.location.replace("/admin.html");
  } catch (error) {
    loginStatus.textContent = error.message || "Не удалось войти.";
    passwordInput.select();
    loginButton.disabled = false;
  }
});
