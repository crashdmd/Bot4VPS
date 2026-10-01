// Справочник не загружает SPA; контракт темы совпадает с settings.js.
const THEME_KEY = 'bot4vps_theme';
const THEME_COLOR = { dark: '#0d1117', light: '#eaeff5', glass: '#0f233b' };
const THEMES = ['dark', 'light', 'glass'];

function panelReturnUrl() {
  try {
    const value = new URLSearchParams(location.search).get('returnTo');
    if (!value || !value.startsWith('/') || value.startsWith('//')) return '/';
    const url = new URL(value, location.origin);
    if (url.origin === location.origin && url.pathname === '/') {
      return `${url.pathname}${url.search}${url.hash}`;
    }
  } catch (_) {}
  return '/';
}

const returnUrl = panelReturnUrl();
document.querySelectorAll('a[href="/"]').forEach(link => { link.href = returnUrl; });

function storedTheme() {
  try {
    const value = localStorage.getItem(THEME_KEY);
    if (THEMES.includes(value)) return value;
    localStorage.setItem(THEME_KEY, 'dark');
  } catch (_) {}
  return 'dark';
}

function applyTheme(value) {
  const resolved = ['light', 'glass'].includes(value) ? value : 'dark';
  if (resolved === 'dark') document.documentElement.removeAttribute('data-theme');
  else document.documentElement.setAttribute('data-theme', resolved);
  document.querySelector('meta[name="theme-color"]')?.setAttribute('content', THEME_COLOR[resolved]);
}

applyTheme(storedTheme());
fetch('/api/settings/theme', { credentials: 'same-origin', cache: 'no-store' })
  .then(response => response.ok ? response.json() : null)
  .then(data => {
    const theme = data?.theme;
    if (THEMES.includes(theme) && theme !== storedTheme()) {
      try { localStorage.setItem(THEME_KEY, theme); } catch (_) {}
      applyTheme(theme);
    }
  })
  .catch(() => {});

const mobile = matchMedia('(max-width:768px)');
const menu = document.getElementById('contents');
const menuToggle = document.getElementById('faq-menu-toggle');
const menuClose = document.getElementById('faq-menu-close');
const backdrop = document.getElementById('faq-menu-backdrop');
const background = document.querySelectorAll('.faq-intro, .faq-articles, .faq-header .faq-brand, .faq-header > .faq-back');

function setMenuOpen(value, restoreFocus = true) {
  const open = mobile.matches && value;
  menu.classList.toggle('open', open);
  backdrop.classList.toggle('open', open);
  document.body.classList.toggle('faq-menu-open', open);
  menuToggle.setAttribute('aria-expanded', String(open));
  menu.inert = mobile.matches && !open;
  background.forEach(element => { element.inert = open; });
  if (mobile.matches) menu.setAttribute('aria-hidden', String(!open));
  else menu.removeAttribute('aria-hidden');
  if (open) {
    menu.setAttribute('role', 'dialog');
    menu.setAttribute('aria-modal', 'true');
    requestAnimationFrame(() => {
      if (menu.classList.contains('open')) menuClose.focus();
    });
  } else {
    menu.removeAttribute('role');
    menu.removeAttribute('aria-modal');
    if (restoreFocus && mobile.matches) menuToggle.focus();
  }
}

menuToggle.addEventListener('click', () => setMenuOpen(!menu.classList.contains('open')));
menuClose.addEventListener('click', () => setMenuOpen(false));
backdrop.addEventListener('click', () => setMenuOpen(false));
menu.querySelectorAll('a').forEach(link => {
  link.addEventListener('click', () => {
    setMenuOpen(false, false);
    if (link.hash) {
      const target = document.getElementById(link.hash.slice(1));
      setActiveTarget(target);
      if (mobile.matches) target?.focus({ preventScroll: true });
    }
  });
});
document.querySelectorAll('.faq-top').forEach(button => {
  button.addEventListener('click', () => setMenuOpen(true));
});
document.addEventListener('keydown', event => {
  if (!menu.classList.contains('open')) return;
  if (event.key === 'Escape') {
    event.preventDefault();
    setMenuOpen(false);
  } else if (event.key === 'Tab') {
    const links = menu.querySelectorAll('button, a[href]');
    const first = links[0];
    const last = links[links.length - 1];
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  }
});
mobile.addEventListener('change', () => {
  setMenuOpen(false, false);
  updateActiveFromScroll();
});
setMenuOpen(false, false);

const tocLinks = [...menu.querySelectorAll('a[href^="#"]')];
const linksById = new Map(tocLinks.map(link => [link.hash.slice(1), link]));
const readingTargets = [...document.querySelectorAll('.faq-article, .faq-article [id][tabindex="-1"]')];
const targetLinks = new Map();
let currentLink = tocLinks[0];
readingTargets.forEach(target => {
  currentLink = linksById.get(target.id) || currentLink;
  targetLinks.set(target.id, currentLink);
});

function setActiveTarget(target) {
  const article = target?.closest('.faq-article');
  const active = targetLinks.get(target?.id) || linksById.get(article?.id) || tocLinks[0];
  tocLinks.forEach(link => {
    if (link === active) link.setAttribute('aria-current', 'location');
    else link.removeAttribute('aria-current');
  });
}

function updateActiveFromScroll() {
  const header = document.querySelector('.faq-header');
  const scrollMargin = parseFloat(window.getComputedStyle?.(readingTargets[0]).scrollMarginTop) || 24;
  const threshold = Math.max(scrollMargin, mobile.matches ? (header?.getBoundingClientRect().height || 0) + 24 : 24) + 1;
  let target = readingTargets[0];
  for (const candidate of readingTargets) {
    if (candidate.getBoundingClientRect().top > threshold) break;
    target = candidate;
  }
  setActiveTarget(target);
}

function updateActiveFromHash() {
  let id = '';
  try { id = decodeURIComponent(location.hash.slice(1)); } catch (_) {}
  const target = document.getElementById(id);
  if (target) setActiveTarget(target);
  else updateActiveFromScroll();
}

let scrollPending = false;
window.addEventListener('scroll', () => {
  if (scrollPending) return;
  scrollPending = true;
  requestAnimationFrame(() => {
    scrollPending = false;
    updateActiveFromScroll();
  });
}, { passive: true });
window.addEventListener('hashchange', updateActiveFromHash);
window.addEventListener('resize', updateActiveFromScroll);
updateActiveFromHash();
