/* Application bootstrap: state, shell, router, search and global events. */

import { api } from "./api.js";
import {
  clearAuth,
  initState,
  refreshFavorites,
  state,
  toggleFavoriteFixture,
  toggleFavoriteTeam,
} from "./state.js";
import {
  renderShell,
  toast,
  updateAuthChrome,
} from "./components.js";
import { getPath, initRetryHandlers, navigate, refresh, startRouter } from "./router.js";
import { $, $$, debounce, esc, fmtTime, icon, leagueLogo, teamLogo } from "./utils.js";

const PROTECTED_PATHS = ["/saved", "/profile", "/admin"];

function renderBootError(message) {
  const app = $("#app");
  if (!app) return;
  app.innerHTML = `
    <div class="boot-screen" style="gap:16px">
      <img src="/assets/logo.svg" alt="" class="boot-logo" />
      <div class="boot-name">BLAQUE <span>ANALYSIS</span></div>
      <p class="small muted" style="max-width:38ch;text-align:center">${esc(message)}</p>
      <button class="btn btn-outline btn-sm" type="button" data-boot-retry>${icon("refresh")} Retry</button>
    </div>
  `;
  $("[data-boot-retry]", app)?.addEventListener("click", () => window.location.reload());
}

/* --------------------------------------------------------------- search */
let searchToken = 0;

function setupSearch() {
  const input = $("#global-search");
  const panel = $("#search-results");
  if (!input || !panel) return;

  const close = () => {
    panel.classList.remove("open");
    panel.innerHTML = "";
  };

  const renderResults = (query, data) => {
    const teams = data.teams || [];
    const leagues = data.leagues || [];
    const fixtures = data.fixtures || [];
    if (!teams.length && !leagues.length && !fixtures.length) {
      panel.innerHTML = `<div class="search-empty">No results for “${esc(query)}”. Try a team or competition name.</div>`;
      panel.classList.add("open");
      return;
    }
    panel.innerHTML = `
      ${
        teams.length
          ? `<div class="search-group-label">Teams</div>${teams
              .map(
                (team) => `
        <a class="search-item" href="#/team/${team.id}">
          ${teamLogo(team, "sm")}
          <span class="search-item-text"><strong>${esc(team.name)}</strong><span>${esc(team.league_slug || "Team")}</span></span>
        </a>`,
              )
              .join("")}`
          : ""
      }
      ${
        leagues.length
          ? `<div class="search-group-label">Competitions</div>${leagues
              .map(
                (league) => `
        <a class="search-item" href="#/league/${esc(league.slug)}">
          ${league.logo ? `<img src="${esc(league.logo)}" alt="" loading="lazy" style="width:22px;height:22px;object-fit:contain" />` : leagueLogo(league)}
          <span class="search-item-text"><strong>${esc(league.name)}</strong><span>${esc(league.country || "International")}</span></span>
        </a>`,
              )
              .join("")}`
          : ""
      }
      ${
        fixtures.length
          ? `<div class="search-group-label">Fixtures</div>${fixtures
              .map(
                (fixture) => `
        <a class="search-item" href="#/match/${fixture.id}">
          <span class="team-logo sm"><span class="fallback">${icon("clock")}</span></span>
          <span class="search-item-text">
            <strong>${esc(fixture.home?.name || "Home")} vs ${esc(fixture.away?.name || "Away")}</strong>
            <span>${esc(fixture.league?.short_name || "Competition")} · ${esc(fmtTime(fixture.kickoff))}</span>
          </span>
        </a>`,
              )
              .join("")}`
          : ""
      }
    `;
    panel.classList.add("open");
  };

  const run = debounce(async (query) => {
    const token = ++searchToken;
    try {
      const data = await api.get(`/search?q=${encodeURIComponent(query)}`, { auth: false, timeout: 20000 });
      if (token !== searchToken) return;
      renderResults(query, data);
    } catch (error) {
      if (token !== searchToken) return;
      panel.innerHTML = `<div class="search-empty">${esc(error.message)}</div>`;
      panel.classList.add("open");
    }
  }, 280);

  input.addEventListener("input", () => {
    const query = input.value.trim();
    if (query.length < 2) {
      searchToken += 1;
      close();
      return;
    }
    run(query);
  });

  input.addEventListener("focus", () => {
    if (panel.innerHTML.trim()) panel.classList.add("open");
  });

  input.addEventListener("keydown", (event) => {
    if (event.key === "Escape") {
      input.blur();
      close();
    }
  });

  document.addEventListener("click", (event) => {
    if (!event.target.closest(".search-wrap")) close();
  });

  panel.addEventListener("click", (event) => {
    if (event.target.closest(".search-item")) close();
  });

  document.addEventListener("keydown", (event) => {
    if (event.key !== "/" || event.metaKey || event.ctrlKey || event.altKey) return;
    const tag = document.activeElement?.tagName;
    if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return;
    event.preventDefault();
    input.focus();
  });
}

/* --------------------------------------------------------------- favorites */
async function handleFavoriteFixture(button) {
  const id = Number(button.dataset.favoriteFixture);
  if (!id) return;
  if (!state.isAuthed) {
    toast("Sign in to save fixtures to your favourites.", "info");
    navigate(`/login?next=${encodeURIComponent(getPath())}`);
    return;
  }
  button.disabled = true;
  try {
    const active = await toggleFavoriteFixture(id);
    $$(`[data-favorite-fixture="${id}"]`).forEach((node) => {
      node.classList.toggle("active", active);
      node.setAttribute("aria-label", active ? "Remove from favourites" : "Add to favourites");
      node.setAttribute("title", active ? "Remove from favourites" : "Add to favourites");
      const label = node.querySelector("[data-favorite-label] span, span");
      if (node.hasAttribute("data-favorite-label") && label) {
        label.textContent = active ? "Saved to favourites" : "Favourite";
      }
    });
    toast(active ? "Fixture added to favourites." : "Fixture removed from favourites.", "success");
  } catch (error) {
    toast(error.message, "error");
  } finally {
    button.disabled = false;
  }
}

async function handleFavoriteTeam(button) {
  const id = Number(button.dataset.favoriteTeam);
  if (!id) return;
  if (!state.isAuthed) {
    toast("Sign in to follow teams.", "info");
    navigate(`/login?next=${encodeURIComponent(getPath())}`);
    return;
  }
  button.disabled = true;
  try {
    const active = await toggleFavoriteTeam(id);
    $$(`[data-favorite-team="${id}"]`).forEach((node) => {
      node.classList.toggle("active", active);
      const label = node.querySelector("span");
      if (node.hasAttribute("data-favorite-team-label") && label) {
        label.textContent = active ? "Favourited" : "Add to favourites";
      }
    });
    toast(active ? "Team added to favourites." : "Team removed from favourites.", "success");
  } catch (error) {
    toast(error.message, "error");
  } finally {
    button.disabled = false;
  }
}

/* --------------------------------------------------------------- tabs */
function setupTabs() {
  document.addEventListener("click", (event) => {
    const tab = event.target.closest("[data-tab-target]");
    if (!tab) return;
    const group = tab.dataset.tabGroup;
    const key = tab.dataset.tabTarget;
    if (!group || !key) return;
    $$(`.tab[data-tab-group="${group}"]`).forEach((node) => {
      const active = node.dataset.tabTarget === key;
      node.classList.toggle("active", active);
      node.setAttribute("aria-selected", active ? "true" : "false");
    });
    $$(`[data-tab-panel][data-tab-group="${group}"]`).forEach((panel) => {
      panel.classList.toggle("active", panel.dataset.tabPanel === key);
    });
  });
}

/* --------------------------------------------------------------- images */
function setupImageFallback() {
  document.addEventListener(
    "error",
    (event) => {
      const img = event.target;
      if (!img || img.tagName !== "IMG" || !img.dataset.fallback) return;
      const fallback = document.createElement("span");
      fallback.className = "fallback";
      fallback.textContent = img.dataset.fallback;
      img.replaceWith(fallback);
    },
    true,
  );
}

/* --------------------------------------------------------------- auth */
let lastUnauthorized = 0;

function setupAuthEvents() {
  document.addEventListener("click", async (event) => {
    const button = event.target.closest("[data-logout]");
    if (!button) return;
    event.preventDefault();
    button.disabled = true;
    try {
      await api.post("/auth/logout", {});
    } catch {
      /* clearing the local session is enough */
    }
    clearAuth();
    updateAuthChrome();
    toast("You have been signed out.", "info");
    navigate("/", { replace: true });
  });

  window.addEventListener("blaque:auth-changed", () => {
    updateAuthChrome();
  });

  window.addEventListener("blaque:unauthorized", () => {
    const now = Date.now();
    if (now - lastUnauthorized < 1500) return;
    lastUnauthorized = now;
    clearAuth();
    updateAuthChrome();
    toast("Your session has expired. Please sign in again.", "info");
    if (PROTECTED_PATHS.some((path) => getPath().startsWith(path))) {
      navigate(`/login?next=${encodeURIComponent(getPath())}`, { replace: true });
    }
  });

  window.addEventListener("blaque:saved-changed", () => {
    if (!state.isAuthed) return;
    api
      .get("/predictions/summary")
      .then((summary) => {
        state.savedSummary = summary;
      })
      .catch(() => {});
    refreshFavorites().catch(() => {});
  });
}

/* --------------------------------------------------------------- misc */
function setupGlobalEvents() {
  initRetryHandlers(document);

  window.addEventListener("blaque:refresh-page", () => refresh());

  window.addEventListener("blaque:toast", (event) => {
    const detail = event.detail || {};
    toast(detail.message || "Something happened.", detail.type || "info");
  });

  document.addEventListener("click", (event) => {
    const target = event.target.closest("[data-href]");
    if (!target) return;
    if (event.target.closest("a, button, input, select, textarea")) return;
    event.preventDefault();
    navigate(target.dataset.href.replace(/^#/, ""));
  });

  document.addEventListener("keydown", (event) => {
    if (event.key !== "Enter" && event.key !== " ") return;
    const target = event.target.closest?.("[data-href]");
    if (!target || event.target.closest("a, button, input, select, textarea")) return;
    event.preventDefault();
    navigate(target.dataset.href.replace(/^#/, ""));
  });

  document.addEventListener("click", (event) => {
    const fixtureButton = event.target.closest("[data-favorite-fixture]");
    if (fixtureButton) {
      event.preventDefault();
      event.stopPropagation();
      handleFavoriteFixture(fixtureButton);
      return;
    }
    const teamButton = event.target.closest("[data-favorite-team]");
    if (teamButton) {
      event.preventDefault();
      event.stopPropagation();
      handleFavoriteTeam(teamButton);
    }
  });
}

/* --------------------------------------------------------------- boot */
async function boot() {
  try {
    await initState();
  } catch (error) {
    console.error("State initialisation failed", error);
    renderBootError("We could not reach the BLAQUE ANALYSIS API. Make sure the server is running, then retry.");
    return;
  }

  const app = $("#app");
  if (!app) return;

  renderShell(app, getPath());
  updateAuthChrome();
  setupSearch();
  setupTabs();
  setupImageFallback();
  setupAuthEvents();
  setupGlobalEvents();
  startRouter();
}

boot();
