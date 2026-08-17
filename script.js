const header = document.querySelector("[data-header]");
const menuToggle = document.querySelector(".menu-toggle");
const siteNav = document.querySelector(".site-nav");

const updateHeader = () => {
  header.classList.toggle("is-scrolled", window.scrollY > 24);
};

updateHeader();
window.addEventListener("scroll", updateHeader, { passive: true });

const closeMenu = () => {
  menuToggle.setAttribute("aria-expanded", "false");
  siteNav.classList.remove("is-open");
  header.classList.remove("menu-is-open");
  document.body.style.overflow = "";
};

menuToggle.addEventListener("click", () => {
  const isOpen = menuToggle.getAttribute("aria-expanded") === "true";
  menuToggle.setAttribute("aria-expanded", String(!isOpen));
  siteNav.classList.toggle("is-open", !isOpen);
  header.classList.toggle("menu-is-open", !isOpen);
  document.body.style.overflow = isOpen ? "" : "hidden";
});

siteNav.querySelectorAll("a").forEach((link) => link.addEventListener("click", closeMenu));

const revealObserver = new IntersectionObserver(
  (entries) => {
    entries.forEach((entry) => {
      if (entry.isIntersecting) {
        entry.target.classList.add("is-visible");
        revealObserver.unobserve(entry.target);
      }
    });
  },
  { threshold: 0.12 }
);

document.querySelectorAll(".reveal").forEach((element, index) => {
  element.style.transitionDelay = `${Math.min(index % 4, 3) * 70}ms`;
  revealObserver.observe(element);
});

const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
const scrollHero = document.querySelector("[data-scroll-hero]");
const scrollPlate = document.querySelector("[data-scroll-plate]");
const plateHalo = document.querySelector(".plate-halo");
const heroCopy = document.querySelector("[data-hero-copy]");
const plateWhisper = document.querySelector("[data-plate-whisper]");
const heroScrollLine = document.querySelector(".hero-scroll-line");
let heroFrame;

const clamp = (value, minimum = 0, maximum = 1) => Math.min(Math.max(value, minimum), maximum);
const smootherStep = (value) => {
  const amount = clamp(value);
  return amount * amount * amount * (amount * (amount * 6 - 15) + 10);
};

const interpolateScene = (progress, frames) => {
  const nextIndex = frames.findIndex((frame) => frame.at >= progress);
  if (nextIndex <= 0) return frames[0];
  const previous = frames[nextIndex - 1];
  const next = frames[nextIndex];
  const segmentProgress = smootherStep((progress - previous.at) / (next.at - previous.at));

  return {
    x: previous.x + (next.x - previous.x) * segmentProgress,
    y: previous.y + (next.y - previous.y) * segmentProgress,
    rotation: previous.rotation + (next.rotation - previous.rotation) * segmentProgress,
    scale: previous.scale + (next.scale - previous.scale) * segmentProgress,
  };
};

const updateHeroScene = () => {
  heroFrame = undefined;
  if (!scrollHero || !scrollPlate || reducedMotion) return;

  const rect = scrollHero.getBoundingClientRect();
  const distance = Math.max(scrollHero.offsetHeight - window.innerHeight, 1);
  const progress = clamp(-rect.top / distance);
  const isMobile = window.innerWidth <= 780;
  const desktopFrames = [
    { at: 0, x: 0, y: 0, rotation: 0, scale: 0.9 },
    { at: 0.42, x: -8, y: -2, rotation: 130, scale: 1.08 },
    { at: 0.68, x: -21, y: 0, rotation: 285, scale: 1.14 },
    { at: 0.86, x: -23, y: 1, rotation: 348, scale: 0.98 },
    { at: 1, x: -23, y: 0, rotation: 360, scale: 0.94 },
  ];
  const mobileFrames = [
    { at: 0, x: 0, y: 0, rotation: 0, scale: 0.9 },
    { at: 0.42, x: 0, y: -3, rotation: 135, scale: 1.03 },
    { at: 0.68, x: 0, y: 0, rotation: 285, scale: 1.08 },
    { at: 0.86, x: 0, y: -1, rotation: 349, scale: 0.88 },
    { at: 1, x: 0, y: -2, rotation: 360, scale: 0.82 },
  ];
  const scene = interpolateScene(progress, isMobile ? mobileFrames : desktopFrames);
  const copyFade = smootherStep((progress - 0.12) / 0.38);
  const haloScale = 1.14 + Math.sin(progress * Math.PI) * 0.1 - progress * 0.05;

  scrollPlate.style.transform = `translate(calc(-50% + ${scene.x}vw), calc(-50% + ${scene.y}vh)) rotate(${scene.rotation}deg) scale(${scene.scale})`;
  if (plateHalo) {
    plateHalo.style.transform = `translate(calc(-50% + ${scene.x * 0.9}vw), calc(-50% + ${scene.y * 0.7}vh)) scale(${haloScale})`;
    plateHalo.style.opacity = String(1 - smootherStep((progress - 0.78) / 0.22) * 0.42);
  }
  heroCopy.style.opacity = String(1 - copyFade);
  heroCopy.style.transform = `translateY(${-copyFade * 38}px)`;
  heroCopy.style.pointerEvents = copyFade > 0.9 ? "none" : "";
  plateWhisper.style.opacity = String(1 - smootherStep(progress / 0.22));
  heroScrollLine.classList.toggle("is-active", progress > 0.26);
  heroScrollLine.classList.toggle("is-settled", progress > 0.84);
};

const requestHeroUpdate = () => {
  if (heroFrame) return;
  heroFrame = requestAnimationFrame(updateHeroScene);
};

updateHeroScene();
window.addEventListener("scroll", requestHeroUpdate, { passive: true });
window.addEventListener("resize", requestHeroUpdate);
