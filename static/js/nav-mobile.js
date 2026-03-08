/**
 * Mobile navigation hamburger toggle.
 * Auto-injects a hamburger button into .top-nav elements.
 * Works with theme.css mobile nav styles.
 */
(function () {
  'use strict';

  function initMobileNav() {
    const nav = document.querySelector('.top-nav');
    if (!nav) return;

    // Inject hamburger button after the brand element
    const btn = document.createElement('button');
    btn.className = 'mobile-menu-btn';
    btn.setAttribute('aria-label', 'Toggle navigation menu');
    btn.setAttribute('aria-expanded', 'false');
    btn.innerHTML = '&#9776;'; // ☰

    const brand = nav.querySelector('.top-nav-brand');
    if (brand) {
      brand.after(btn);
    } else {
      nav.prepend(btn);
    }

    // Toggle menu open/closed
    btn.addEventListener('click', function (e) {
      e.stopPropagation();
      const isOpen = nav.classList.toggle('mobile-open');
      btn.setAttribute('aria-expanded', isOpen ? 'true' : 'false');
      btn.innerHTML = isOpen ? '&#10005;' : '&#9776;'; // ✕ or ☰
    });

    // Close when clicking outside the nav
    document.addEventListener('click', function (e) {
      if (!nav.contains(e.target)) {
        nav.classList.remove('mobile-open');
        btn.setAttribute('aria-expanded', 'false');
        btn.innerHTML = '&#9776;';
      }
    });

    // Close when a nav link is clicked (for SPA-style navigation)
    nav.querySelectorAll('.top-nav-link').forEach(function (link) {
      link.addEventListener('click', function () {
        nav.classList.remove('mobile-open');
        btn.setAttribute('aria-expanded', 'false');
        btn.innerHTML = '&#9776;';
      });
    });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initMobileNav);
  } else {
    initMobileNav();
  }
})();
