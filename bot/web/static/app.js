// English Tutor Mini App Frontend Controller

const tg = window.Telegram?.WebApp;

const urlParams = new URLSearchParams(window.location.search);
const initialFilter = urlParams.get('filter') || "all";

const state = {
  token: localStorage.getItem("english_bot_token") || "",
  user: null,
  stats: null,
  words: [],
  searchQuery: "",
  activeFilter: initialFilter,
  activeSort: "next_review",
  selectedPos: "",
  isLoading: false,
};

// DOM Elements
const el = {
  userStreak: document.getElementById("user-streak"),
  statTotal: document.getElementById("stat-total"),
  statDue: document.getElementById("stat-due"),
  statLearning: document.getElementById("stat-learning"),
  statMastered: document.getElementById("stat-mastered"),
  searchInput: document.getElementById("search-input"),
  searchClear: document.getElementById("search-clear"),
  filterToggleBtn: document.getElementById("filter-toggle-btn"),
  filtersRow: document.getElementById("filters-row"),
  filterChips: document.querySelectorAll(".chip"),
  sortSelect: document.getElementById("sort-select"),
  wordsContainer: document.getElementById("words-container"),
  loadingSpinner: document.getElementById("loading-spinner"),
  emptyState: document.getElementById("empty-state"),
  trainBtn: document.getElementById("train-btn"),
  authModal: document.getElementById("auth-modal"),
  fullWordModal: document.getElementById("full-word-modal"),
  fullWordClose: document.getElementById("full-word-close"),
  fullWordBody: document.getElementById("full-word-body"),
};

// --- Initialization ---
document.addEventListener("DOMContentLoaded", async () => {
  if (tg) {
    tg.ready();
    tg.expand();
    if (tg.setHeaderColor) tg.setHeaderColor("secondary_bg_color");
    if (tg.setBackgroundColor) tg.setBackgroundColor("bg_color");
  }

  setupEventListeners();
  await authenticateAndLoad();
});

// --- Authentication ---
async function authenticateAndLoad() {
  setLoading(true);

  // 1. Try Telegram WebApp initData
  if (tg && tg.initData && tg.initData.length > 0) {
    try {
      const resp = await fetch("/api/auth/telegram", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ init_data: tg.initData }),
      });

      if (resp.ok) {
        const data = await resp.json();
        state.token = data.token;
        state.user = data.user;
        localStorage.setItem("english_bot_token", data.token);
      } else {
        console.error("Telegram auth failed", await resp.text());
      }
    } catch (err) {
      console.error("Auth network error", err);
    }
  }

  // 2. Check if we have token
  if (!state.token) {
    // Show non-tg fallback modal
    if (el.authModal) el.authModal.style.display = "flex";
    setLoading(false);
    return;
  }

  if (el.authModal) el.authModal.style.display = "none";

  // Load User, Stats, and Words
  await Promise.all([loadUserProfile(), loadStats(), loadWords()]);
  setLoading(false);
}

// --- API Calls ---
async function apiFetch(endpoint, options = {}) {
  const headers = {
    "Content-Type": "application/json",
    Authorization: `Bearer ${state.token}`,
    ...(options.headers || {}),
  };

  const resp = await fetch(endpoint, { ...options, headers });
  if (resp.status === 401) {
    localStorage.removeItem("english_bot_token");
    state.token = "";
    if (el.authModal) el.authModal.style.display = "flex";
    throw new Error("Unauthorized");
  }
  return resp;
}

async function loadUserProfile() {
  try {
    const resp = await apiFetch("/api/me");
    if (resp.ok) {
      state.user = await resp.json();
      renderUserProfile();
    }
  } catch (err) {
    console.warn("Could not load user profile", err);
  }
}

async function loadStats() {
  try {
    const resp = await apiFetch("/api/stats");
    if (resp.ok) {
      state.stats = await resp.json();
      renderStats();
    }
  } catch (err) {
    console.warn("Could not load stats", err);
  }
}

async function loadWords() {
  try {
    const params = new URLSearchParams({
      filter: state.activeFilter,
      sort: state.activeSort,
      q: state.searchQuery,
      limit: "200",
    });
    if (state.selectedPos) {
      params.append("pos", state.selectedPos);
    }

    const resp = await apiFetch(`/api/words?${params.toString()}`);
    if (resp.ok) {
      const data = await resp.json();
      state.words = data.words;
      renderWords();
    }
  } catch (err) {
    console.error("Could not load words", err);
  }
}

// --- Rendering ---
function renderUserProfile() {
  if (!state.user) return;
  el.userStreak.textContent = `🔥 ${state.user.streak || 0} дн.`;
}

function renderStats() {
  if (!state.stats) return;
  el.statTotal.textContent = state.stats.total_words;
  el.statDue.textContent = state.stats.due_words;
  el.statLearning.textContent = state.stats.learning_words;
  el.statMastered.textContent = state.stats.mastered_words;
}

function renderWords() {
  if (!state.words || state.words.length === 0) {
    el.wordsContainer.innerHTML = "";
    el.emptyState.style.display = "block";
    return;
  }

  el.emptyState.style.display = "none";
  el.wordsContainer.innerHTML = state.words.map((w) => createWordCardHtml(w)).join("");

  // Attach audio event listeners
  document.querySelectorAll(".audio-btn").forEach((btn) => {
    btn.addEventListener("click", (e) => {
      e.stopPropagation();
      const word = btn.dataset.word;
      playPronunciation(word, btn);
    });
  });
}

function createWordCardHtml(word) {
  const rep = word.repetition || 0;
  const maxBars = 5;
  const filledBars = Math.min(maxBars, rep);
  let barColorClass = rep >= 3 ? "" : rep >= 1 ? "medium" : "low";

  let barsHtml = "";
  for (let i = 0; i < maxBars; i++) {
    const isFilled = i < filledBars;
    barsHtml += `<div class="retention-scale-segment ${isFilled ? `filled ${barColorClass}` : ""}"></div>`;
  }

  return `
    <div class="word-card" id="word-${word.id}">
      <div class="retention-scale-x" title="Уровень запоминания: ${rep}/5">
        ${barsHtml}
      </div>
      
      <div class="word-card-inner">
        <div class="word-card-left">
          <div class="word-title-group">
            <div class="word-canonical">${escapeHtml(word.canonical_word)}</div>
            <button class="audio-btn" data-word="${escapeHtml(word.canonical_word)}" title="Произношение">
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5"></polygon>
                <path d="M15.54 8.46a5 5 0 0 1 0 7.07"></path>
                <path d="M19.07 4.93a10 10 0 0 1 0 14.14"></path>
              </svg>
            </button>
          </div>
          <div class="word-translation">${escapeHtml(word.translation)}</div>
        </div>
        
        <div class="word-card-right">
          <button class="open-full-card-btn" data-id="${word.id}" title="Подробнее">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"></path>
              <polyline points="15 3 21 3 21 9"></polyline>
              <line x1="10" y1="14" x2="21" y2="3"></line>
            </svg>
          </button>
        </div>
      </div>
    </div>
  `;
}

// --- Audio Player ---
let currentAudio = null;
function playPronunciation(word, btnEl) {
  if (currentAudio) {
    currentAudio.pause();
    currentAudio = null;
  }

  document.querySelectorAll(".audio-btn").forEach((b) => b.classList.remove("playing"));
  if (btnEl) btnEl.classList.add("playing");

  const audioUrl = `/api/tts/${encodeURIComponent(word)}`;
  const audio = new Audio(audioUrl);
  currentAudio = audio;

  audio.onended = () => {
    if (btnEl) btnEl.classList.remove("playing");
  };

  audio.onerror = () => {
    if (btnEl) btnEl.classList.remove("playing");
    // Fallback to Web Speech API
    if ("speechSynthesis" in window) {
      const utterance = new SpeechSynthesisUtterance(word);
      utterance.lang = "en-US";
      window.speechSynthesis.speak(utterance);
    }
  };

  audio.play().catch(() => {
    // If blocked or network error, try speech synthesis
    if (btnEl) btnEl.classList.remove("playing");
    if ("speechSynthesis" in window) {
      const utterance = new SpeechSynthesisUtterance(word);
      utterance.lang = "en-US";
      window.speechSynthesis.speak(utterance);
    }
  });
}

// --- Event Handlers & Search Debounce ---
function setupEventListeners() {
  // Initialize filter chips state
  el.filterChips.forEach((chip) => {
    if (chip.dataset.filter === state.activeFilter) {
      chip.classList.add("active");
    } else {
      chip.classList.remove("active");
    }
  });

  // Search
  let searchTimer = null;
  el.searchInput.addEventListener("input", (e) => {
    const val = e.target.value;
    state.searchQuery = val;
    el.searchClear.style.display = val.length > 0 ? "block" : "none";

    clearTimeout(searchTimer);
    searchTimer = setTimeout(() => {
      loadWords();
    }, 250);
  });

  el.searchClear.addEventListener("click", () => {
    el.searchInput.value = "";
    state.searchQuery = "";
    el.searchClear.style.display = "none";
    loadWords();
  });

  el.filterToggleBtn.addEventListener("click", () => {
    if (el.filtersRow.style.display === "none") {
      el.filtersRow.style.display = "flex";
      el.filterToggleBtn.classList.add("active");
    } else {
      el.filtersRow.style.display = "none";
      el.filterToggleBtn.classList.remove("active");
    }
  });

  // Filter chips
  el.filterChips.forEach((chip) => {
    chip.addEventListener("click", () => {
      el.filterChips.forEach((c) => c.classList.remove("active"));
      chip.classList.add("active");
      state.activeFilter = chip.dataset.filter;
      loadWords();
    });
  });

  // Sort select
  el.sortSelect.addEventListener("change", (e) => {
    state.activeSort = e.target.value;
    loadWords();
  });

  // Train button in bot
  if (el.trainBtn) {
    el.trainBtn.addEventListener("click", (e) => {
      e.preventDefault();
      if (tg) {
        tg.close();
      } else {
        window.location.href = "https://t.me/EnglishTutor_AI_bot?start=quiz";
      }
    });
  }
}

function setLoading(isLoading) {
  state.isLoading = isLoading;
  if (el.loadingSpinner) {
    el.loadingSpinner.style.display = isLoading ? "flex" : "none";
  }
}

// --- Helpers ---
function escapeHtml(text) {
  if (!text) return "";
  const map = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#039;" };
  return String(text).replace(/[&<>"']/g, (m) => map[m]);
}

function escapeRegExp(string) {
  return string.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

// --- Full Word Modal Logic ---
document.addEventListener("click", (e) => {
  const btn = e.target.closest(".open-full-card-btn");
  if (btn) {
    const id = btn.dataset.id;
    const word = state.words.find(w => String(w.id) === String(id));
    if (word) openFullWordModal(word);
  }
});

el.fullWordClose?.addEventListener("click", () => {
  el.fullWordModal.style.display = "none";
});

el.fullWordModal?.addEventListener("click", (e) => {
  if (e.target === el.fullWordModal) {
    el.fullWordModal.style.display = "none";
  }
});

function openFullWordModal(word) {
  if (!el.fullWordModal || !el.fullWordBody) return;
  
  const rep = word.repetition || 0;
  const ef = (word.easiness_factor || 2.5).toFixed(2);
  const interval = word.interval || 1;
  const created = new Date(word.created_at).toLocaleDateString('ru-RU');

  // Examples (show all in modal)
  let examplesHtml = "";
  if (word.examples && word.examples.length > 0) {
    const exItems = word.examples.map(ex => {
      const enText = typeof ex === "string" ? ex : ex.target || ex.en || "";
      const ruText = typeof ex === "object" ? ex.native || ex.ru || "" : "";
      const regex = new RegExp(`(${escapeRegExp(word.canonical_word)}|${escapeRegExp(word.lemma || "")})`, "gi");
      const highlightedEn = enText.replace(regex, "<strong>$1</strong>");
      return `
        <div class="full-modal-example">
          <div class="example-en">${highlightedEn}</div>
          ${ruText ? `<div class="example-ru">${ruText}</div>` : ""}
        </div>
      `;
    }).join("");
    examplesHtml = `<div class="full-modal-section"><h4>Примеры</h4>${exItems}</div>`;
  }

  // Tags
  let tagsHtml = "";
  if (word.synonyms_collocations && word.synonyms_collocations.length > 0) {
    tagsHtml = `
      <div class="full-modal-section">
        <h4>Синонимы / Словосочетания</h4>
        <div class="tags-row" style="margin-top: 8px;">
          ${word.synonyms_collocations.map((t) => `<span class="tag-pill">${escapeHtml(t)}</span>`).join("")}
        </div>
      </div>
    `;
  }

  // Definition
  let definitionHtml = "";
  if (word.definition || word.definition_native) {
    definitionHtml = `
      <div class="full-modal-section">
        <h4>Значение</h4>
        ${word.definition ? `<div class="modal-text-en">${escapeHtml(word.definition)}</div>` : ""}
        ${word.definition_native ? `<div class="modal-text-ru">${escapeHtml(word.definition_native)}</div>` : ""}
      </div>
    `;
  }

  // Grammar Notes
  let grammarHtml = "";
  const allGrammar = [...(word.grammar_notes || []), ...(word.grammar_notes_native || [])];
  if (allGrammar.length > 0) {
    grammarHtml = `
      <div class="full-modal-section">
        <h4>Грамматика</h4>
        <ul class="modal-list">
          ${allGrammar.map(g => `<li>${escapeHtml(g)}</li>`).join("")}
        </ul>
      </div>
    `;
  }

  el.fullWordBody.innerHTML = `
    <div class="full-modal-header-row" style="justify-content: flex-start; gap: 8px;">
      <h2 class="full-modal-word">${escapeHtml(word.canonical_word)}</h2>
      <button class="audio-btn modal-audio-btn" data-word="${escapeHtml(word.canonical_word)}" title="Произношение">
        <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5"></polygon>
          <path d="M15.54 8.46a5 5 0 0 1 0 7.07"></path>
          <path d="M19.07 4.93a10 10 0 0 1 0 14.14"></path>
        </svg>
      </button>
    </div>
    
    <div class="full-modal-badges">
      ${word.pos ? `<span class="word-pos">${escapeHtml(word.pos)}</span>` : ""}
      ${word.transcription ? `<span class="word-transcription">[${escapeHtml(word.transcription)}]</span>` : ""}
    </div>

    <div class="full-modal-translation">${escapeHtml(word.translation)}</div>
    
    ${definitionHtml}
    ${grammarHtml}
    ${examplesHtml}
    ${tagsHtml}
    
    <div class="full-modal-section">
      <h4>Статистика (SM-2)</h4>
      <div class="stats-grid">
        <div class="stat-box">
          <div class="stat-value">${rep}</div>
          <div class="stat-label">Повторений</div>
        </div>
        <div class="stat-box">
          <div class="stat-value">${interval} дн.</div>
          <div class="stat-label">Интервал</div>
        </div>
        <div class="stat-box">
          <div class="stat-value">${ef}</div>
          <div class="stat-label">Фактор</div>
        </div>
        <div class="stat-box">
          <div class="stat-value">${created}</div>
          <div class="stat-label">Добавлено</div>
        </div>
      </div>
    </div>
  `;

  // Attach audio for modal
  const audioBtn = el.fullWordBody.querySelector(".modal-audio-btn");
  if (audioBtn) {
    audioBtn.addEventListener("click", (e) => {
      e.stopPropagation();
      playPronunciation(word.canonical_word, audioBtn);
    });
  }

  el.fullWordModal.style.display = "flex";
}
