import { useCallback, useEffect, useMemo, useState } from "react";
import "./App.css";

const API_BASE_URL = "http://127.0.0.1:8000";
const TOKEN_KEY = "entqra_access_token";

function getStoredToken() {
  return (
    localStorage.getItem(TOKEN_KEY) ||
    sessionStorage.getItem(TOKEN_KEY)
  );
}

function normalizeWebsite(url) {
  if (!url) return "";
  const value = String(url).trim();
  if (!value) return "";
  return /^https?:\/\//i.test(value) ? value : `https://${value}`;
}

function renderLeadershipText(text) {
  const value = String(text || "");
  const parts = value.split(/(Current CEO|Former CEO|CEO|Chief Executive Officer|Co-Founder|Co-Founder[s]?|Founder|Founders|President|Chief Business Officer|Chief Marketing Officer)/gi);
  return parts.map((part, index) =>
    /^(Current CEO|Former CEO|CEO|Chief Executive Officer|Co-Founder|Co-Founders|Founder|Founders|President|Chief Business Officer|Chief Marketing Officer)$/i.test(part)
      ? <strong key={`role-${index}`}>{part}</strong>
      : <span key={`text-${index}`}>{part}</span>
  );
}

function getItemText(item) {
  if (!item) return "";
  if (typeof item === "string") return item;

  return (
    item.text ||
    item.sentence ||
    item.evidence ||
    item.claim ||
    item.description ||
    item.summary ||
    item.value ||
    item.name ||
    item.title ||
    ""
  );
}

function formatConfidence(confidence) {
  const score = Number(confidence?.score);
  const level = String(confidence?.level || "unknown").replace(/[-_]/g, " ");
  return {
    level: level.toUpperCase(),
    score: Number.isFinite(score) ? `${Math.round(score * 100)}%` : "—",
  };
}

function ResearchGraph({ graph, subject }) {
  const nodes = Array.isArray(graph?.nodes) ? graph.nodes : [];
  const edges = Array.isArray(graph?.edges) ? graph.edges : [];
  if (!nodes.length) {
    return <p className="entqra-muted">No evidence-backed relationships were strong enough to visualize yet.</p>;
  }

  const rootIndex = Math.max(0, nodes.findIndex((node) => node.id === "root"));
  const root = nodes[rootIndex] || nodes[0];
  const others = nodes.filter((node) => node.id !== root.id).slice(0, 10);
  const width = 860;
  const height = 430;
  const cx = width / 2;
  const cy = height / 2;
  const radiusX = Math.min(315, 145 + others.length * 16);
  const radiusY = 145;
  const positions = new Map([[root.id, { x: cx, y: cy }]]);
  others.forEach((node, index) => {
    const angle = (-Math.PI / 2) + (index / Math.max(1, others.length)) * Math.PI * 2;
    positions.set(node.id, {
      x: cx + Math.cos(angle) * radiusX,
      y: cy + Math.sin(angle) * radiusY,
    });
  });

  const visibleEdges = edges.filter((edge) => positions.has(edge.source) && positions.has(edge.target)).slice(0, 18);
  const short = (value, max = 22) => {
    const text = String(value || "");
    return text.length > max ? `${text.slice(0, max - 1)}…` : text;
  };

  return (
    <div className="entqra-graph-wrap">
      <svg className="entqra-graph" viewBox={`0 0 ${width} ${height}`} role="img" aria-label={`Relationship graph for ${subject || root.name}`}>
        <defs>
          <marker id="entqra-arrow" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto">
            <path d="M0,0 L8,4 L0,8 Z" fill="rgba(125,153,255,.62)" />
          </marker>
        </defs>
        {visibleEdges.map((edge, index) => {
          const a = positions.get(edge.source);
          const b = positions.get(edge.target);
          const midX = (a.x + b.x) / 2;
          const midY = (a.y + b.y) / 2;
          return (
            <g key={`edge-${index}`}>
              <line x1={a.x} y1={a.y} x2={b.x} y2={b.y} className="entqra-graph-edge" markerEnd="url(#entqra-arrow)" />
              <text x={midX} y={midY - 7} textAnchor="middle" className="entqra-graph-edge-label">
                {short(edge.relationship || "related to", 18)}
              </text>
            </g>
          );
        })}
        {others.map((node) => {
          const pos = positions.get(node.id);
          return (
            <g key={node.id} transform={`translate(${pos.x},${pos.y})`}>
              <circle r="33" className="entqra-graph-node" />
              <text y="4" textAnchor="middle" className="entqra-graph-node-text">{short(node.name, 15)}</text>
            </g>
          );
        })}
        <g transform={`translate(${cx},${cy})`}>
          <circle r="52" className="entqra-graph-root" />
          <text y="5" textAnchor="middle" className="entqra-graph-root-text">{short(root.name || subject, 18)}</text>
        </g>
      </svg>
      <div className="entqra-graph-legend">
        <span><i className="entqra-legend-root" /> researched entity</span>
        <span><i className="entqra-legend-node" /> connected entity</span>
        <span><i className="entqra-legend-line" /> evidence-backed relationship</span>
      </div>
    </div>
  );
}

function App() {
  const [showPassword, setShowPassword] = useState(false);
  const [rememberMe, setRememberMe] = useState(false);

  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");

  const [loading, setLoading] = useState(false);
  const [checkingAuth, setCheckingAuth] = useState(true);

  const [errorMessage, setErrorMessage] = useState("");
  const [successMessage, setSuccessMessage] = useState("");

  const [currentUser, setCurrentUser] = useState(null);

  const [entities, setEntities] = useState([]);
  const [relationships, setRelationships] = useState([]);

  const [dashboardLoading, setDashboardLoading] = useState(false);

  // =========================================================
  // ENTQRA LIVE INTELLIGENCE
  // =========================================================

  const [intelligenceQuery, setIntelligenceQuery] = useState("");
  const [intelligenceLoading, setIntelligenceLoading] = useState(false);
  const [intelligenceResult, setIntelligenceResult] = useState(null);
  const [intelligenceError, setIntelligenceError] = useState("");

  // =========================================================
  // DASHBOARD NAVIGATION
  // =========================================================

  const [activeSection, setActiveSection] = useState("overview");

  // =========================================================
  // DISCOVER ENTITIES
  // =========================================================

  const [discoverySearch, setDiscoverySearch] = useState("");
  const [discoveryFilter, setDiscoveryFilter] = useState("all");

  // =========================================================
  // ENTITY INTELLIGENCE
  // =========================================================

  const [selectedEntity, setSelectedEntity] = useState(null);

  // =========================================================
  // CLEAR AUTHENTICATION
  // =========================================================

  const clearAuthentication = useCallback(() => {
    localStorage.removeItem(TOKEN_KEY);
    sessionStorage.removeItem(TOKEN_KEY);

    setCurrentUser(null);
    setEntities([]);
    setRelationships([]);
    setActiveSection("overview");
    setIntelligenceQuery("");
    setIntelligenceResult(null);
    setIntelligenceError("");
  }, []);

  // =========================================================
  // LOAD DASHBOARD DATA
  // =========================================================

  const loadDashboardData = useCallback(async (token) => {
    if (!token) {
      return;
    }

    try {
      setDashboardLoading(true);

      const [entitiesResponse, relationshipsResponse] =
        await Promise.all([
          fetch(`${API_BASE_URL}/entities`, {
            method: "GET",
            headers: {
              Authorization: `Bearer ${token}`,
            },
          }),

          fetch(`${API_BASE_URL}/relationships`, {
            method: "GET",
            headers: {
              Authorization: `Bearer ${token}`,
            },
          }),
        ]);

      if (entitiesResponse.ok) {
        const entitiesData = await entitiesResponse.json();

        setEntities(entitiesData.entities || []);
      } else {
        setEntities([]);
      }

      if (relationshipsResponse.ok) {
        const relationshipsData =
          await relationshipsResponse.json();

        setRelationships(
          relationshipsData.relationships || []
        );
      } else {
        setRelationships([]);
      }
    } catch (error) {
      console.error(
        "Failed to load dashboard data:",
        error
      );
    } finally {
      setDashboardLoading(false);
    }
  }, []);

  // =========================================================
  // CHECK AUTHENTICATION
  // =========================================================

  const checkAuthentication = useCallback(
    async (token) => {
      try {
        const response = await fetch(
          `${API_BASE_URL}/me`,
          {
            method: "GET",
            headers: {
              Authorization: `Bearer ${token}`,
            },
          }
        );

        if (!response.ok) {
          clearAuthentication();
          return;
        }

        const data = await response.json();

        setCurrentUser(data.user);

        await loadDashboardData(token);
      } catch (error) {
        console.error(
          "Authentication check failed:",
          error
        );

        clearAuthentication();
      } finally {
        setCheckingAuth(false);
      }
    },
    [clearAuthentication, loadDashboardData]
  );

  // =========================================================
  // CHECK EXISTING AUTHENTICATION
  // =========================================================

  useEffect(() => {
    const token = getStoredToken();

    if (!token) {
      window.setTimeout(() => {
        setCheckingAuth(false);
      }, 0);

      return;
    }

    window.setTimeout(() => {
      checkAuthentication(token);
    }, 0);
  }, [checkAuthentication]);

  // =========================================================
  // LOGIN
  // =========================================================

  const handleSubmit = async (event) => {
    event.preventDefault();

    setErrorMessage("");
    setSuccessMessage("");

    const normalizedEmail = email.trim().toLowerCase();

    if (!normalizedEmail || !password) {
      setErrorMessage(
        "Please enter your email and password."
      );
      return;
    }

    try {
      setLoading(true);

      const response = await fetch(
        `${API_BASE_URL}/login`,
        {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
          },
          body: JSON.stringify({
            email: normalizedEmail,
            password,
          }),
        }
      );

      const data = await response.json();

      if (!response.ok) {
        const message =
          typeof data.detail === "string"
            ? data.detail
            : "Invalid email or password.";

        throw new Error(message);
      }

      const token = data.access_token;

      if (!token) {
        throw new Error(
          "Login succeeded, but no access token was received."
        );
      }

      // =====================================================
      // STORE TOKEN
      // =====================================================

      if (rememberMe) {
        localStorage.setItem(TOKEN_KEY, token);
        sessionStorage.removeItem(TOKEN_KEY);
      } else {
        sessionStorage.setItem(TOKEN_KEY, token);
        localStorage.removeItem(TOKEN_KEY);
      }

      // =====================================================
      // GET CURRENT USER
      // =====================================================

      const meResponse = await fetch(
        `${API_BASE_URL}/me`,
        {
          method: "GET",
          headers: {
            Authorization: `Bearer ${token}`,
          },
        }
      );

      if (!meResponse.ok) {
        throw new Error(
          "Authentication succeeded, but user information could not be loaded."
        );
      }

      const meData = await meResponse.json();

      setCurrentUser(meData.user);

      // =====================================================
      // LOAD DASHBOARD
      // =====================================================

      await loadDashboardData(token);

      setActiveSection("overview");

      // =====================================================
      // SUCCESS
      // =====================================================

      setSuccessMessage(
        "Login successful. Welcome back!"
      );

      setPassword("");
    } catch (error) {
      console.error("Login error:", error);

      setErrorMessage(
        error?.message ||
          "Unable to connect to the ENTQRA server."
      );
    } finally {
      setLoading(false);
    }
  };

  // =========================================================
  // LOGOUT
  // =========================================================

  const handleLogout = () => {
    clearAuthentication();

    setEmail("");
    setPassword("");

    setErrorMessage("");
    setSuccessMessage("");
  };

  // =========================================================
  // GOOGLE LOGIN
  // =========================================================

  const handleGoogleLogin = () => {
    setErrorMessage("");
    setSuccessMessage("");

    setErrorMessage(
      "Google sign-in will be connected when OAuth is configured."
    );
  };

  // =========================================================
  // CREATE ACCOUNT
  // =========================================================

  const handleCreateAccount = () => {
    setErrorMessage("");
    setSuccessMessage("");

    setErrorMessage(
      "Registration page will be created in the next authentication step."
    );
  };

  // =========================================================
  // FORGOT PASSWORD
  // =========================================================

  const handleForgotPassword = () => {
    setErrorMessage("");
    setSuccessMessage("");

    setErrorMessage(
      "Password recovery will be available in the next authentication step."
    );
  };

  // =========================================================
  // LIVE INTELLIGENCE RESEARCH
  // =========================================================

  const handleIntelligenceSearch = async (event) => {
    if (event) {
      event.preventDefault();
    }

    const query = intelligenceQuery.trim();

    if (!query) {
      setIntelligenceError("Enter a question or topic to research.");
      setActiveSection("insights");
      return;
    }

    const token = getStoredToken();

    if (!token) {
      setIntelligenceError("Your session has expired. Please log in again.");
      return;
    }

    try {
      setIntelligenceLoading(true);
      setIntelligenceError("");
      setActiveSection("insights");

      const response = await fetch(
        `${API_BASE_URL}/intelligence/search`,
        {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            Authorization: `Bearer ${token}`,
          },
          body: JSON.stringify({
            query,
            max_sources: 10,
          }),
        }
      );

      const data = await response.json();

      if (!response.ok) {
        const detail = data?.detail;
        const message =
          typeof detail === "string"
            ? detail
            : detail?.message ||
              data?.message ||
              "EntQra could not complete the research.";
        throw new Error(message);
      }

      setIntelligenceResult(data);
    } catch (error) {
      console.error("EntQra intelligence research failed:", error);
      setIntelligenceResult(null);
      setIntelligenceError(
        error?.message ||
          "Unable to connect to the EntQra intelligence engine."
      );
    } finally {
      setIntelligenceLoading(false);
    }
  };

  // =========================================================
  // NAVIGATION
  // =========================================================

  const handleNavigation = (section) => {
    setActiveSection(section);

    setDiscoverySearch("");
    setDiscoveryFilter("all");

    if (section !== "entity") {
      setSelectedEntity(null);
    }
  };

  // =========================================================
  // ENTITY INTELLIGENCE
  // =========================================================

  const handleViewEntity = (entity) => {
    setErrorMessage("");
    setSuccessMessage("");
    setSelectedEntity(entity);
    setActiveSection("entity");
  };

  const handleBackToDiscover = () => {
    setSelectedEntity(null);
    setActiveSection("discover");
    setErrorMessage("");
    setSuccessMessage("");
  };

  // =========================================================
  // DISCOVERY FILTERS
  // =========================================================

  const entityTypes = useMemo(() => {
    const types = entities
      .map((entity) => entity.entity_type)
      .filter(Boolean);

    return [...new Set(types)];
  }, [entities]);

  const filteredEntities = useMemo(() => {
    const search = discoverySearch
      .trim()
      .toLowerCase();

    return entities.filter((entity) => {
      const matchesSearch =
        !search ||
        String(entity.name || "")
          .toLowerCase()
          .includes(search) ||
        String(entity.entity_type || "")
          .toLowerCase()
          .includes(search) ||
        String(entity.category || "")
          .toLowerCase()
          .includes(search);

      const matchesFilter =
        discoveryFilter === "all" ||
        entity.entity_type === discoveryFilter;

      return matchesSearch && matchesFilter;
    });
  }, [
    entities,
    discoverySearch,
    discoveryFilter,
  ]);

  // =========================================================
  // AUTHENTICATION CHECK SCREEN
  // =========================================================

  if (checkingAuth) {
    return (
      <main className="auth-loading-page">
        <div className="auth-loading-card">
          <div className="auth-loading-logo">
            ENT<span>Q</span>RA
          </div>

          <div className="auth-loading-spinner" />

          <p>Connecting to EntQra...</p>
        </div>
      </main>
    );
  }

  // =========================================================
  // DASHBOARD
  // =========================================================

  if (currentUser) {
    return (
      <main className="dashboard-page">

        {/* =================================================
            SIDEBAR
            ================================================= */}

        <aside className="dashboard-sidebar">

          <div className="dashboard-brand">
            ENT<span>Q</span>RA
          </div>

          <div className="sidebar-label">
            INTELLIGENCE
          </div>

          <nav className="dashboard-nav">

            {/* OVERVIEW */}

            <button
              type="button"
              className={`nav-item ${
                activeSection === "overview"
                  ? "active"
                  : ""
              }`}
              onClick={() =>
                handleNavigation("overview")
              }
            >
              <svg
                viewBox="0 0 32 32"
                aria-hidden="true"
              >
                <rect
                  x="5"
                  y="5"
                  width="9"
                  height="9"
                  rx="2"
                />

                <rect
                  x="18"
                  y="5"
                  width="9"
                  height="9"
                  rx="2"
                />

                <rect
                  x="5"
                  y="18"
                  width="9"
                  height="9"
                  rx="2"
                />

                <rect
                  x="18"
                  y="18"
                  width="9"
                  height="9"
                  rx="2"
                />
              </svg>

              <span>Overview</span>
            </button>

            {/* DISCOVER ENTITIES */}

            <button
              type="button"
              className={`nav-item ${
                activeSection === "discover"
                  ? "active"
                  : ""
              }`}
              onClick={() =>
                handleNavigation("discover")
              }
            >
              <svg
                viewBox="0 0 32 32"
                aria-hidden="true"
              >
                <circle
                  cx="14"
                  cy="14"
                  r="8"
                />

                <path d="M20 20L27 27" />
              </svg>

              <span>Discover Entities</span>
            </button>

            {/* RELATIONSHIPS */}

            <button
              type="button"
              className={`nav-item ${
                activeSection === "relationships"
                  ? "active"
                  : ""
              }`}
              onClick={() =>
                handleNavigation("relationships")
              }
            >
              <svg
                viewBox="0 0 32 32"
                aria-hidden="true"
              >
                <circle
                  cx="8"
                  cy="16"
                  r="3"
                />

                <circle
                  cx="24"
                  cy="8"
                  r="3"
                />

                <circle
                  cx="24"
                  cy="24"
                  r="3"
                />

                <path d="M11 15L21 9" />
                <path d="M11 17L21 23" />
              </svg>

              <span>Relationships</span>
            </button>

            {/* INSIGHTS */}

            <button
              type="button"
              className={`nav-item ${
                activeSection === "insights"
                  ? "active"
                  : ""
              }`}
              onClick={() =>
                handleNavigation("insights")
              }
            >
              <svg
                viewBox="0 0 32 32"
                aria-hidden="true"
              >
                <path d="M6 26V18" />
                <path d="M13 26V13" />
                <path d="M20 26V8" />
                <path d="M27 26V4" />
              </svg>

              <span>Insights</span>
            </button>

          </nav>

          <div className="sidebar-bottom">

            {/* SETTINGS */}

            <button
              type="button"
              className={`nav-item ${
                activeSection === "settings"
                  ? "active"
                  : ""
              }`}
              onClick={() =>
                handleNavigation("settings")
              }
            >
              <svg
                viewBox="0 0 32 32"
                aria-hidden="true"
              >
                <path d="M16 4V8" />
                <path d="M16 24V28" />
                <path d="M4 16H8" />
                <path d="M24 16H28" />

                <circle
                  cx="16"
                  cy="16"
                  r="6"
                />
              </svg>

              <span>Settings</span>
            </button>

            {/* LOGOUT */}

            <button
              type="button"
              className="nav-item logout-item"
              onClick={handleLogout}
            >
              <svg
                viewBox="0 0 32 32"
                aria-hidden="true"
              >
                <path d="M19 6H25C26.1 6 27 6.9 27 8V24C27 25.1 26.1 26 25 26H19" />
                <path d="M14 16H27" />
                <path d="M18 11L13 16L18 21" />
                <path d="M13 16H5" />
              </svg>

              <span>Logout</span>
            </button>

          </div>
        </aside>

        {/* =================================================
            MAIN DASHBOARD
            ================================================= */}

        <section className="dashboard-main">

          {/* =================================================
              OVERVIEW
              ================================================= */}

          {activeSection === "overview" && (
            <>
              {/* HEADER */}

              <header className="dashboard-header">

                <div>

                  <p className="dashboard-eyebrow">
                    ENTITY INTELLIGENCE PLATFORM
                  </p>

                  <h1>
                    Good to see you,{" "}
                    <span>
                      {currentUser.name || "User"}
                    </span>
                  </h1>

                  <p className="dashboard-welcome">
                    Explore, verify and understand
                    real-world entities.
                  </p>

                </div>

                <div className="dashboard-user">

                  <div className="user-avatar">
                    {currentUser.name
                      ?.charAt(0)
                      ?.toUpperCase() || "U"}
                  </div>

                  <div className="user-details">

                    <strong>
                      {currentUser.name || "User"}
                    </strong>

                    <span>
                      {currentUser.email || ""}
                    </span>

                  </div>

                  <button
                    type="button"
                    className="header-logout"
                    onClick={handleLogout}
                    aria-label="Logout"
                  >
                    <svg
                      viewBox="0 0 32 32"
                      aria-hidden="true"
                    >
                      <path d="M19 6H25C26.1 6 27 6.9 27 8V24C27 25.1 26.1 26 25 26H19" />
                      <path d="M14 16H27" />
                      <path d="M18 11L13 16L18 21" />
                      <path d="M13 16H5" />
                    </svg>
                  </button>

                </div>

              </header>

              {/* SEARCH / ASK ENTQRA */}

              <form
                className="dashboard-search"
                onSubmit={handleIntelligenceSearch}
              >

                <div className="dashboard-search-icon">

                  <svg
                    viewBox="0 0 32 32"
                    aria-hidden="true"
                  >
                    <circle
                      cx="14"
                      cy="14"
                      r="8"
                    />

                    <path d="M20 20L27 27" />
                  </svg>

                </div>

                <input
                  type="text"
                  value={intelligenceQuery}
                  onChange={(event) =>
                    setIntelligenceQuery(event.target.value)
                  }
                  placeholder="Ask EntQra anything to research..."
                  aria-label="Ask EntQra anything to research"
                />

                <button
                  type="submit"
                  disabled={intelligenceLoading}
                >
                  {intelligenceLoading ? "Researching..." : "Search"}
                </button>

              </form>

              {/* STATISTICS */}

              <div className="stats-grid">

                <div className="stat-card">

                  <div className="stat-icon blue">

                    <svg
                      viewBox="0 0 32 32"
                      aria-hidden="true"
                    >
                      <rect
                        x="5"
                        y="5"
                        width="9"
                        height="9"
                        rx="2"
                      />

                      <rect
                        x="18"
                        y="5"
                        width="9"
                        height="9"
                        rx="2"
                      />

                      <rect
                        x="5"
                        y="18"
                        width="9"
                        height="9"
                        rx="2"
                      />

                      <rect
                        x="18"
                        y="18"
                        width="9"
                        height="9"
                        rx="2"
                      />
                    </svg>

                  </div>

                  <div>

                    <span>Total Entities</span>

                    <strong>
                      {dashboardLoading
                        ? "..."
                        : entities.length}
                    </strong>

                  </div>

                </div>

                <div className="stat-card">

                  <div className="stat-icon purple">

                    <svg
                      viewBox="0 0 32 32"
                      aria-hidden="true"
                    >
                      <circle
                        cx="8"
                        cy="16"
                        r="3"
                      />

                      <circle
                        cx="24"
                        cy="8"
                        r="3"
                      />

                      <circle
                        cx="24"
                        cy="24"
                        r="3"
                      />

                      <path d="M11 15L21 9" />
                      <path d="M11 17L21 23" />
                    </svg>

                  </div>

                  <div>

                    <span>Relationships</span>

                    <strong>
                      {dashboardLoading
                        ? "..."
                        : relationships.length}
                    </strong>

                  </div>

                </div>

                <div className="stat-card">

                  <div className="stat-icon cyan">

                    <svg
                      viewBox="0 0 32 32"
                      aria-hidden="true"
                    >
                      <path d="M16 4L27 8V15C27 22 22 27 16 29C10 27 5 22 5 15V8L16 4Z" />

                      <path d="M10.5 16L14 19.5L21.5 12" />
                    </svg>

                  </div>

                  <div>

                    <span>Verified Data</span>

                    <strong>Active</strong>

                  </div>

                </div>

                <div className="stat-card">

                  <div className="stat-icon violet">

                    <svg
                      viewBox="0 0 32 32"
                      aria-hidden="true"
                    >
                      <path d="M6 26V18" />
                      <path d="M13 26V13" />
                      <path d="M20 26V8" />
                      <path d="M27 26V4" />
                    </svg>

                  </div>

                  <div>

                    <span>AI Insights</span>

                    <strong>Ready</strong>

                  </div>

                </div>

              </div>

              {/* CONTENT GRID */}

              <div className="dashboard-content-grid">

                {/* RECENT ENTITIES */}

                <div className="dashboard-panel entities-panel">

                  <div className="panel-header">

                    <div>

                      <span className="panel-label">
                        ENTITY DATABASE
                      </span>

                      <h2>
                        Recent Entities
                      </h2>

                    </div>

                    <button
                      type="button"
                      className="panel-action"
                      onClick={() =>
                        handleNavigation("discover")
                      }
                    >
                      View All
                    </button>

                  </div>

                  {entities.length === 0 ? (

                    <div className="empty-state">

                      <div className="empty-icon">

                        <svg
                          viewBox="0 0 32 32"
                          aria-hidden="true"
                        >
                          <circle
                            cx="14"
                            cy="14"
                            r="8"
                          />

                          <path d="M20 20L27 27" />
                        </svg>

                      </div>

                      <strong>
                        No entities yet
                      </strong>

                      <span>
                        Start discovering entities to
                        build your intelligence graph.
                      </span>

                    </div>

                  ) : (

                    <div className="entity-list">

                      {entities
                        .slice(0, 5)
                        .map((entity) => (

                          <div
                            className="entity-row"
                            key={entity.id}
                          >

                            <div className="entity-avatar">

                              {entity.name
                                ?.charAt(0)
                                ?.toUpperCase() || "E"}

                            </div>

                            <div className="entity-info">

                              <strong>
                                {entity.name}
                              </strong>

                              <span>
                                {entity.entity_type}

                                {entity.category
                                  ? ` • ${entity.category}`
                                  : ""}
                              </span>

                            </div>

                            <span className="entity-status">
                              Verified
                            </span>

                          </div>

                        ))}

                    </div>

                  )}

                </div>

                {/* RELATIONSHIPS */}

                <div className="dashboard-panel relationship-panel">

                  <div className="panel-header">

                    <div>

                      <span className="panel-label">
                        KNOWLEDGE GRAPH
                      </span>

                      <h2>
                        Relationships
                      </h2>

                    </div>

                    <div className="relationship-count">
                      {relationships.length}
                    </div>

                  </div>

                  {relationships.length === 0 ? (

                    <div className="empty-state compact">

                      <div className="empty-icon">

                        <svg
                          viewBox="0 0 32 32"
                          aria-hidden="true"
                        >
                          <circle
                            cx="8"
                            cy="16"
                            r="3"
                          />

                          <circle
                            cx="24"
                            cy="8"
                            r="3"
                          />

                          <circle
                            cx="24"
                            cy="24"
                            r="3"
                          />

                          <path d="M11 15L21 9" />
                          <path d="M11 17L21 23" />
                        </svg>

                      </div>

                      <strong>
                        No relationships yet
                      </strong>

                      <span>
                        Connections between entities
                        will appear here.
                      </span>

                    </div>

                  ) : (

                    <div className="relationship-list">

                      {relationships
                        .slice(0, 5)
                        .map((relationship) => (

                          <div
                            className="relationship-row"
                            key={relationship.id}
                          >

                            <div className="relationship-entities">

                              <strong>
                                {
                                  relationship.source_entity_name
                                }
                              </strong>

                              <span>
                                {
                                  relationship.relationship_type
                                }
                              </span>

                              <strong>
                                {
                                  relationship.target_entity_name
                                }
                              </strong>

                            </div>

                          </div>

                        ))}

                    </div>

                  )}

                </div>

              </div>

              {/* AI SECTION */}

              <div className="ai-dashboard-card">

                <div className="ai-glow" />

                <div className="ai-icon">

                  <svg
                    viewBox="0 0 32 32"
                    aria-hidden="true"
                  >
                    <path d="M16 4L18.5 12.5L27 15L18.5 17.5L16 26L13.5 17.5L5 15L13.5 12.5L16 4Z" />

                    <path d="M25 4V9" />
                    <path d="M22.5 6.5H27.5" />
                  </svg>

                </div>

                <div className="ai-content">

                  <span className="panel-label">
                    ENTQRA INTELLIGENCE
                  </span>

                  <h2>
                    Intelligent insights are ready.
                  </h2>

                  <p>
                    Discover patterns, connections and
                    contextual intelligence across your
                    entity network.
                  </p>

                </div>

                <button
                  type="button"
                  className="ai-button"
                  onClick={() =>
                    handleNavigation("insights")
                  }
                >
                  Explore Intelligence

                  <svg
                    viewBox="0 0 32 32"
                    aria-hidden="true"
                  >
                    <path d="M5 16H26" />
                    <path d="M18 8L26 16L18 24" />
                  </svg>

                </button>

              </div>
            </>
          )}

          {/* =================================================
              DISCOVER ENTITIES
              ================================================= */}

          {activeSection === "discover" && (
            <div className="discover-page">

              <header className="discover-header">

                <p className="discover-eyebrow">
                  ENTITY DISCOVERY
                </p>

                <h1>
                  Discover{" "}
                  <span>Entities.</span>
                </h1>

                <p className="discover-description">
                  Search, explore and verify entities
                  across your intelligence database.
                </p>

              </header>

              {/* SEARCH CARD */}

              <div className="discovery-search-card">

                <h2 className="discovery-search-title">
                  Search the Entity Database
                </h2>

                <p className="discovery-search-subtitle">
                  Find companies, people, organizations
                  and other real-world entities.
                </p>

                <div className="discovery-search">

                  <div className="discovery-search-icon">

                    <svg
                      viewBox="0 0 32 32"
                      aria-hidden="true"
                    >
                      <circle
                        cx="14"
                        cy="14"
                        r="8"
                      />

                      <path d="M20 20L27 27" />
                    </svg>

                  </div>

                  <input
                    type="text"
                    value={discoverySearch}
                    onChange={(event) =>
                      setDiscoverySearch(
                        event.target.value
                      )
                    }
                    placeholder="Search by entity name, type or category..."
                  />

                  {discoverySearch && (
                    <button
                      type="button"
                      onClick={() =>
                        setDiscoverySearch("")
                      }
                      style={{
                        background: "transparent",
                        color: "#71809d",
                        boxShadow: "none",
                        marginRight: "4px",
                      }}
                    >
                      Clear
                    </button>
                  )}

                </div>

                {/* FILTERS */}

                <div className="discovery-filters">

                  <button
                    type="button"
                    className={`discovery-filter ${
                      discoveryFilter === "all"
                        ? "active"
                        : ""
                    }`}
                    onClick={() =>
                      setDiscoveryFilter("all")
                    }
                  >
                    All
                  </button>

                  {entityTypes.map((type) => (

                    <button
                      type="button"
                      key={type}
                      className={`discovery-filter ${
                        discoveryFilter === type
                          ? "active"
                          : ""
                      }`}
                      onClick={() =>
                        setDiscoveryFilter(type)
                      }
                    >
                      {type}
                    </button>

                  ))}

                </div>

              </div>

              {/* RESULTS HEADER */}

              <div className="discovery-results-header">

                <div>

                  <span className="discovery-results-label">
                    INTELLIGENCE DATABASE
                  </span>

                  <h2 className="discovery-results-title">
                    {discoverySearch
                      ? "Search Results"
                      : "Available Entities"}
                  </h2>

                </div>

                <span className="discovery-results-count">
                  {filteredEntities.length}{" "}
                  {filteredEntities.length === 1
                    ? "ENTITY"
                    : "ENTITIES"}
                </span>

              </div>

              {/* RESULTS */}

              {dashboardLoading ? (

                <div className="discovery-empty">

                  <div className="discovery-spinner" />

                  <strong>
                    Loading entities...
                  </strong>

                  <span>
                    Connecting to the EntQra intelligence
                    database.
                  </span>

                </div>

              ) : filteredEntities.length === 0 ? (

                <div className="discovery-empty">

                  <div className="discovery-empty-icon">

                    <svg
                      viewBox="0 0 32 32"
                      aria-hidden="true"
                    >
                      <circle
                        cx="14"
                        cy="14"
                        r="8"
                      />

                      <path d="M20 20L27 27" />
                    </svg>

                  </div>

                  <strong>
                    {entities.length === 0
                      ? "No entities available"
                      : "No matching entities"}
                  </strong>

                  <span>
                    {entities.length === 0
                      ? "Your entity database is currently empty. Start discovering entities to build your intelligence graph."
                      : "Try a different search term or choose another entity type."}
                  </span>

                </div>

              ) : (

                <div className="discovery-results-grid">

                  {filteredEntities.map((entity) => (

                    <article
                      className="discovery-entity-card"
                      key={entity.id}
                    >

                      <div className="discovery-entity-top">

                        <div className="discovery-entity-avatar">
                          {entity.name
                            ?.charAt(0)
                            ?.toUpperCase() || "E"}
                        </div>

                        <div className="discovery-entity-heading">

                          <strong>
                            {entity.name || "Unknown Entity"}
                          </strong>

                          <span>
                            {entity.entity_type ||
                              "Entity"}

                            {entity.category
                              ? ` • ${entity.category}`
                              : ""}
                          </span>

                        </div>

                        <span className="discovery-verified">
                          Verified
                        </span>

                      </div>

                      <p className="discovery-entity-description">
                        {entity.description ||
                          "Verified entity information is available in the EntQra intelligence database."}
                      </p>

                      <div className="discovery-entity-footer">

                        <span className="discovery-entity-meta">
                          ENTITY ID:{" "}
                          {entity.id ?? "N/A"}
                        </span>

                        <button
                          type="button"
                          className="discovery-view-button"
                          onClick={() =>
                            handleViewEntity(entity)
                          }
                        >
                          View Entity
                        </button>

                      </div>

                    </article>

                  ))}

                </div>

              )}

            </div>
          )}

          {/* =================================================
              ENTITY INTELLIGENCE
              ================================================= */}

          {activeSection === "entity" && selectedEntity && (
            <div className="entity-intelligence-page">

              <button
                type="button"
                className="entity-back-button"
                onClick={handleBackToDiscover}
              >
                <svg viewBox="0 0 32 32" aria-hidden="true">
                  <path d="M26 16H7" />
                  <path d="M14 8L6 16L14 24" />
                </svg>
                Back to Discover
              </button>

              <header className="entity-intelligence-header">

                <div className="entity-intelligence-heading">
                  <div className="entity-intelligence-avatar">
                    {selectedEntity.name
                      ?.charAt(0)
                      ?.toUpperCase() || "E"}
                  </div>

                  <div>
                    <div className="entity-intelligence-eyebrow">
                      ENTITY INTELLIGENCE
                    </div>

                    <h1>
                      {selectedEntity.name || "Unknown Entity"}
                    </h1>

                    <div className="entity-intelligence-subtitle">
                      {selectedEntity.entity_type || "Entity"}
                      {selectedEntity.category
                        ? ` • ${selectedEntity.category}`
                        : ""}
                    </div>
                  </div>
                </div>

                <div className="entity-intelligence-verified">
                  <svg viewBox="0 0 32 32" aria-hidden="true">
                    <path d="M16 3L27 7V15C27 22 22.5 27 16 29C9.5 27 5 22 5 15V7L16 3Z" />
                    <path d="M10.5 16L14 19.5L21.5 12" />
                  </svg>

                  <div>
                    <strong>Verified Entity</strong>
                    <span>Trusted intelligence record</span>
                  </div>
                </div>

              </header>

              <div className="entity-intelligence-grid">

                <section className="entity-intelligence-card entity-overview-card">
                  <div className="entity-intelligence-card-header">
                    <div>
                      <span className="panel-label">
                        VERIFIED PROFILE
                      </span>
                      <h2>Entity Overview</h2>
                    </div>

                    <span className="entity-record-id">
                      ID: {selectedEntity.id ?? "N/A"}
                    </span>
                  </div>

                  <p className="entity-intelligence-description">
                    {selectedEntity.description ||
                      "Verified entity information is available in the EntQra intelligence database. This profile brings together the core identity, classification and contextual information available for this entity."}
                  </p>

                  <div className="entity-facts-grid">
                    <div className="entity-fact">
                      <span>Entity Type</span>
                      <strong>
                        {selectedEntity.entity_type || "Not available"}
                      </strong>
                    </div>

                    <div className="entity-fact">
                      <span>Category</span>
                      <strong>
                        {selectedEntity.category || "Not available"}
                      </strong>
                    </div>

                    <div className="entity-fact">
                      <span>Verification</span>
                      <strong className="verified-text">
                        Verified
                      </strong>
                    </div>

                    <div className="entity-fact">
                      <span>Record ID</span>
                      <strong>
                        {selectedEntity.id ?? "N/A"}
                      </strong>
                    </div>
                  </div>
                </section>

                <section className="entity-intelligence-card">
                  <div className="entity-intelligence-card-header">
                    <div>
                      <span className="panel-label">
                        INTELLIGENCE STATUS
                      </span>
                      <h2>Data Confidence</h2>
                    </div>

                    <div className="entity-confidence-badge">
                      HIGH
                    </div>
                  </div>

                  <div className="entity-confidence">
                    <div className="entity-confidence-ring">
                      <div>
                        <strong>Verified</strong>
                        <span>Data state</span>
                      </div>
                    </div>

                    <div className="entity-confidence-copy">
                      <strong>Trusted intelligence record</strong>
                      <p>
                        EntQra has a verified entity record
                        available for analysis.
                      </p>

                      <div className="entity-status-line">
                        <span />
                        Sources ready for analysis
                      </div>
                    </div>
                  </div>
                </section>

                <section className="entity-intelligence-card entity-relationships-card">
                  <div className="entity-intelligence-card-header">
                    <div>
                      <span className="panel-label">
                        KNOWLEDGE GRAPH
                      </span>
                      <h2>Connected Relationships</h2>
                    </div>

                    <div className="relationship-count">
                      {relationships.filter(
                        (relationship) =>
                          String(
                            relationship.source_entity_name || ""
                          ).toLowerCase() ===
                            String(
                              selectedEntity.name || ""
                            ).toLowerCase() ||
                          String(
                            relationship.target_entity_name || ""
                          ).toLowerCase() ===
                            String(
                              selectedEntity.name || ""
                            ).toLowerCase()
                      ).length}
                    </div>
                  </div>

                  {relationships.filter(
                    (relationship) =>
                      String(
                        relationship.source_entity_name || ""
                      ).toLowerCase() ===
                        String(
                          selectedEntity.name || ""
                        ).toLowerCase() ||
                      String(
                        relationship.target_entity_name || ""
                      ).toLowerCase() ===
                        String(
                          selectedEntity.name || ""
                        ).toLowerCase()
                  ).length === 0 ? (

                    <div className="entity-intelligence-empty">
                      <div className="entity-intelligence-empty-icon">
                        <svg viewBox="0 0 32 32" aria-hidden="true">
                          <circle cx="8" cy="16" r="3" />
                          <circle cx="24" cy="8" r="3" />
                          <circle cx="24" cy="24" r="3" />
                          <path d="M11 15L21 9" />
                          <path d="M11 17L21 23" />
                        </svg>
                      </div>

                      <strong>No direct relationships found</strong>

                      <span>
                        Connections for this entity will appear
                        here as the knowledge graph grows.
                      </span>
                    </div>

                  ) : (

                    <div className="entity-relationship-list">
                      {relationships
                        .filter(
                          (relationship) =>
                            String(
                              relationship.source_entity_name || ""
                            ).toLowerCase() ===
                              String(
                                selectedEntity.name || ""
                              ).toLowerCase() ||
                            String(
                              relationship.target_entity_name || ""
                            ).toLowerCase() ===
                              String(
                                selectedEntity.name || ""
                              ).toLowerCase()
                        )
                        .map((relationship) => (
                          <div
                            className="entity-relationship-row"
                            key={relationship.id}
                          >
                            <div className="entity-relationship-node">
                              <span className="entity-node-dot" />
                              <strong>
                                {relationship.source_entity_name}
                              </strong>
                            </div>

                            <div className="entity-relationship-type">
                              <span>
                                {relationship.relationship_type ||
                                  "CONNECTED TO"}
                              </span>

                              <svg viewBox="0 0 32 32" aria-hidden="true">
                                <path d="M5 16H26" />
                                <path d="M18 8L26 16L18 24" />
                              </svg>
                            </div>

                            <div className="entity-relationship-node">
                              <span className="entity-node-dot" />
                              <strong>
                                {relationship.target_entity_name}
                              </strong>
                            </div>
                          </div>
                        ))}
                    </div>
                  )}
                </section>

                <section className="entity-intelligence-card entity-ai-card">
                  <div className="entity-ai-glow" />

                  <div className="entity-ai-icon">
                    <svg viewBox="0 0 32 32" aria-hidden="true">
                      <path d="M16 4L18.5 12.5L27 15L18.5 17.5L16 26L13.5 17.5L5 15L13.5 12.5L16 4Z" />
                      <path d="M25 4V9" />
                      <path d="M22.5 6.5H27.5" />
                    </svg>
                  </div>

                  <div className="entity-ai-content">
                    <span className="panel-label">
                      ENTQRA AI ENGINE
                    </span>

                    <h2>Intelligence layer ready.</h2>

                    <p>
                      AI-powered contextual reasoning, pattern
                      detection and deeper entity analysis will
                      operate on this verified intelligence record.
                    </p>

                    <div className="entity-ai-features">
                      <span>
                        <i />
                        Context Analysis
                      </span>

                      <span>
                        <i />
                        Pattern Detection
                      </span>

                      <span>
                        <i />
                        Relationship Reasoning
                      </span>
                    </div>
                  </div>

                  <button
                    type="button"
                    className="entity-ai-button"
                    onClick={() => handleNavigation("insights")}
                  >
                    Explore AI Insights

                    <svg viewBox="0 0 32 32" aria-hidden="true">
                      <path d="M5 16H26" />
                      <path d="M18 8L26 16L18 24" />
                    </svg>
                  </button>
                </section>

              </div>
            </div>
          )}

          {/* =================================================
              RELATIONSHIPS
              ================================================= */}

          {activeSection === "relationships" && (
            <div className="discover-page">

              <header className="discover-header">

                <p className="discover-eyebrow">
                  KNOWLEDGE GRAPH
                </p>

                <h1>
                  Entity{" "}
                  <span>Relationships.</span>
                </h1>

                <p className="discover-description">
                  Explore connections between entities
                  in your intelligence graph.
                </p>

              </header>

              <div className="dashboard-panel relationship-panel">

                <div className="panel-header">

                  <div>

                    <span className="panel-label">
                      RELATIONSHIP DATABASE
                    </span>

                    <h2>
                      All Relationships
                    </h2>

                  </div>

                  <div className="relationship-count">
                    {relationships.length}
                  </div>

                </div>

                {relationships.length === 0 ? (

                  <div className="discovery-empty">

                    <div className="discovery-empty-icon">

                      <svg
                        viewBox="0 0 32 32"
                        aria-hidden="true"
                      >
                        <circle
                          cx="8"
                          cy="16"
                          r="3"
                        />

                        <circle
                          cx="24"
                          cy="8"
                          r="3"
                        />

                        <circle
                          cx="24"
                          cy="24"
                          r="3"
                        />

                        <path d="M11 15L21 9" />
                        <path d="M11 17L21 23" />
                      </svg>

                    </div>

                    <strong>
                      No relationships yet
                    </strong>

                    <span>
                      Connections between entities
                      will appear here once they are
                      discovered.
                    </span>

                  </div>

                ) : (

                  <div className="relationship-list">

                    {relationships.map(
                      (relationship) => (

                        <div
                          className="relationship-row"
                          key={relationship.id}
                        >

                          <div className="relationship-entities">

                            <strong>
                              {
                                relationship.source_entity_name
                              }
                            </strong>

                            <span>
                              {
                                relationship.relationship_type
                              }
                            </span>

                            <strong>
                              {
                                relationship.target_entity_name
                              }
                            </strong>

                          </div>

                        </div>

                      )
                    )}

                  </div>

                )}

              </div>

            </div>
          )}

          {/* =================================================
              INSIGHTS / LIVE INTELLIGENCE
              ================================================= */}

          {activeSection === "insights" && (
            <div className="discover-page entqra-intelligence-page">

              <style>{`
                .entqra-intelligence-page { padding-bottom: 52px; }
                .entqra-research-form {
                  display: flex; gap: 12px; align-items: center; margin: 28px 0 22px;
                  padding: 9px; border: 1px solid rgba(104,129,190,.22); border-radius: 18px;
                  background: rgba(8,16,38,.72); box-shadow: 0 18px 45px rgba(0,0,0,.18);
                }
                .entqra-research-form input {
                  flex: 1; min-width: 0; border: 0; outline: 0; background: transparent;
                  color: inherit; padding: 15px 12px; font-size: 15px;
                }
                .entqra-research-form button {
                  border: 0; border-radius: 12px; padding: 13px 20px; cursor: pointer;
                  font-weight: 750; color: white; background: linear-gradient(135deg,#3478ff,#7046ff);
                  box-shadow: 0 10px 24px rgba(73,91,255,.22);
                }
                .entqra-research-form button:disabled { opacity: .65; cursor: wait; }
                .entqra-research-error {
                  margin: -6px 0 20px; padding: 13px 15px; border-radius: 12px;
                  border: 1px solid rgba(255,93,125,.3); background: rgba(255,93,125,.08); color: #ffb4c3;
                }
                .entqra-answer-card {
                  position: relative; overflow: hidden; padding: 28px; border-radius: 22px;
                  border: 1px solid rgba(92,127,226,.25);
                  background: linear-gradient(135deg,rgba(31,64,137,.38),rgba(55,31,111,.38));
                  box-shadow: 0 24px 60px rgba(0,0,0,.2);
                }
                .entqra-answer-card::after {
                  content: ""; position: absolute; width: 180px; height: 180px; right: -70px; top: -80px;
                  border-radius: 50%; background: rgba(116,86,255,.14); filter: blur(8px);
                }
                .entqra-section-label {
                  display: flex; justify-content: space-between; align-items: center; gap: 16px; margin-bottom: 10px;
                }
                .entqra-section-label > span:first-child {
                  font-size: 11px; letter-spacing: .16em; font-weight: 800; opacity: .68;
                }
                .entqra-confidence {
                  display: inline-flex; align-items: center; gap: 8px; padding: 7px 10px; border-radius: 999px;
                  background: rgba(86,220,170,.11); border: 1px solid rgba(86,220,170,.22);
                  font-size: 11px; font-weight: 800; text-transform: uppercase; letter-spacing: .08em;
                }
                .entqra-confidence-dot { width: 7px; height: 7px; border-radius: 50%; background: currentColor; }
                .entqra-answer { max-width: 1000px; margin: 0; line-height: 1.78; font-size: 17px; color: rgba(255,255,255,.92); }
                .entqra-confidence-rationale { margin: 15px 0 0; color: rgba(207,219,245,.72); font-size: 13px; line-height: 1.6; }
                .entqra-research-grid {
                  display: grid; grid-template-columns: minmax(0,1.45fr) minmax(280px,.75fr); gap: 18px; margin-top: 18px;
                }
                .entqra-card {
                  padding: 22px; border-radius: 18px; border: 1px solid rgba(104,129,190,.18);
                  background: rgba(7,15,35,.66);
                }
                .entqra-card h3 { margin: 4px 0 18px; font-size: 18px; }
                .entqra-findings { display: grid; gap: 2px; }
                .entqra-finding {
                  display: grid; grid-template-columns: 34px minmax(0,1fr); gap: 12px; align-items: start;
                  padding: 13px 0; border-bottom: 1px solid rgba(104,129,190,.12);
                }
                .entqra-finding:last-child { border-bottom: 0; }
                .entqra-finding-number {
                  display: grid; place-items: center; width: 30px; height: 30px; border-radius: 9px;
                  background: rgba(74,115,255,.13); color: #8eb2ff; font-size: 11px; font-weight: 800;
                }
                .entqra-finding-text { line-height: 1.55; color: rgba(235,240,255,.86); font-size: 14px; }
                .entqra-signals { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
                .entqra-signal {
                  padding: 14px; border-radius: 13px; background: rgba(255,255,255,.025);
                  border: 1px solid rgba(104,129,190,.11);
                }
                .entqra-signal span { display: block; font-size: 11px; color: rgba(178,193,225,.66); margin-bottom: 7px; }
                .entqra-signal strong { font-size: 20px; }
                .entqra-status {
                  margin-top: 12px; padding: 12px 14px; border-radius: 12px;
                  background: rgba(86,220,170,.06); color: rgba(198,231,218,.82); font-size: 12px;
                }
                .entqra-evidence-list,.entqra-source-list { display: grid; gap: 12px; }
                .entqra-evidence-item,.entqra-source-item {
                  padding: 16px; border-radius: 14px; background: rgba(255,255,255,.025);
                  border: 1px solid rgba(104,129,190,.11);
                }
                .entqra-evidence-item p,.entqra-source-item p {
                  margin: 0; line-height: 1.6; font-size: 13px; color: rgba(222,231,250,.78);
                }
                .entqra-evidence-meta {
                  display: flex; justify-content: space-between; gap: 12px; margin-top: 9px;
                  font-size: 11px; color: rgba(164,181,218,.64);
                }
                .entqra-source-head { display: flex; justify-content: space-between; gap: 14px; align-items: flex-start; margin-bottom: 8px; }
                .entqra-source-title { font-weight: 750; color: rgba(247,249,255,.95); text-decoration: none; }
                .entqra-source-title:hover { text-decoration: underline; }
                .entqra-source-domain { font-size: 11px; color: rgba(164,181,218,.64); margin-top: 3px; }
                .entqra-source-quality {
                  flex: 0 0 auto; padding: 5px 8px; border-radius: 999px; font-size: 10px; font-weight: 800;
                  letter-spacing: .07em; text-transform: uppercase; background: rgba(89,127,255,.1); color: #a9c1ff;
                }
                .entqra-source-footer {
                  display: flex; justify-content: space-between; gap: 12px; align-items: center; margin-top: 11px;
                  font-size: 11px; color: rgba(164,181,218,.64);
                }
                .entqra-source-footer a { color: #9db7ff; text-decoration: none; }
                .entqra-source-footer a:hover { text-decoration: underline; }
                .entqra-entity-context { display: flex; flex-wrap: wrap; gap: 9px; }
                .entqra-entity-chip {
                  border: 1px solid rgba(104,129,190,.16); background: rgba(255,255,255,.025); color: inherit;
                  border-radius: 11px; padding: 10px 12px; cursor: pointer; text-align: left;
                }
                .entqra-entity-chip strong,.entqra-entity-chip span { display: block; }
                .entqra-entity-chip span { margin-top: 3px; font-size: 10px; opacity: .58; }
                .entqra-empty-research {
                  padding: 42px 24px; text-align: center; border-radius: 18px;
                  border: 1px dashed rgba(104,129,190,.2); background: rgba(7,15,35,.4);
                }
                .entqra-empty-research strong,.entqra-empty-research span { display: block; }
                .entqra-empty-research span { margin-top: 8px; color: rgba(178,193,225,.68); font-size: 13px; }
                .entqra-muted { color: rgba(178,193,225,.66); font-size: 13px; line-height: 1.6; }

                .entqra-profile-hero {
                  display: grid; grid-template-columns: minmax(0,1fr) auto; gap: 20px; align-items: start;
                  padding: 24px; margin-bottom: 18px; border-radius: 20px;
                  border: 1px solid rgba(104,129,190,.2); background: rgba(7,15,35,.78);
                }
                .entqra-profile-kicker { font-size: 11px; letter-spacing: .14em; text-transform: uppercase; color: #8ca9e8; font-weight: 800; }
                .entqra-profile-name { margin: 7px 0 5px; font-size: 30px; line-height: 1.1; }
                .entqra-profile-meta { color: rgba(178,193,225,.7); font-size: 12px; }
                .entqra-profile-description { margin: 14px 0 0; max-width: 900px; line-height: 1.7; color: rgba(230,236,250,.82); }
                .entqra-profile-badge { padding: 8px 11px; border-radius: 999px; border: 1px solid rgba(104,129,190,.18); background: rgba(75,110,210,.1); font-size: 10px; font-weight: 800; text-transform: uppercase; letter-spacing: .08em; }
                .entqra-dossier { display: grid; gap: 18px; }
                .entqra-dossier-section { padding: 22px; border-radius: 18px; border: 1px solid rgba(104,129,190,.16); background: rgba(7,15,35,.58); }
                .entqra-dossier-section h3 { margin: 4px 0 14px; }
                .entqra-dossier-item { display: grid; grid-template-columns: 8px minmax(0,1fr); gap: 12px; padding: 12px 0; border-bottom: 1px solid rgba(104,129,190,.1); }
                .entqra-dossier-item:last-child { border-bottom: 0; }
                .entqra-dossier-dot { width: 8px; height: 8px; margin-top: 7px; border-radius: 50%; background: #7398ff; box-shadow: 0 0 12px rgba(115,152,255,.45); }
                .entqra-dossier-text { line-height: 1.68; font-size: 14px; color: rgba(232,238,252,.86); }
                .entqra-dossier-source { margin-top: 6px; font-size: 10px; color: rgba(164,181,218,.58); }
                .entqra-method { margin-top: 18px; font-size: 11px; color: rgba(164,181,218,.58); }
                .entqra-profile-identity { display: flex; gap: 18px; align-items: flex-start; }
                .entqra-profile-logo-wrap { position: relative; width: 72px; height: 72px; flex: 0 0 72px; }
                .entqra-profile-logo,.entqra-profile-logo-fallback { position: absolute; inset: 0; width: 72px; height: 72px; border-radius: 18px; }
                .entqra-profile-logo { object-fit: contain; padding: 9px; box-sizing: border-box; background: rgba(255,255,255,.94); }
                .entqra-profile-logo-fallback { display: grid; place-items: center; background: linear-gradient(135deg,rgba(60,120,255,.26),rgba(118,78,255,.25)); border: 1px solid rgba(120,150,255,.25); font-size: 27px; font-weight: 850; color: #eef3ff; }
                .entqra-profile-website { display: inline-flex; margin-top: 13px; color: #9db7ff; text-decoration: none; font-size: 12px; font-weight: 750; }
                .entqra-profile-website:hover { text-decoration: underline; }
                .entqra-answer p { margin: 0 0 14px; }
                .entqra-answer p:last-child { margin-bottom: 0; }
                .entqra-key-findings-card { margin-top: 18px; }
                .entqra-section-intro,.entqra-section-question { color: rgba(178,193,225,.68); line-height: 1.65; font-size: 13px; margin: -8px 0 15px; }
                .entqra-finding { grid-template-columns: 34px minmax(0,1fr); }
                .entqra-finding-text { margin: 0; line-height: 1.7; }
                .entqra-overview-section { padding: 24px; }
                .entqra-overview-grid { display: grid; grid-template-columns: repeat(2,minmax(0,1fr)); gap: 12px; }
                .entqra-overview-fact { padding: 15px; border: 1px solid rgba(104,129,190,.12); border-radius: 14px; background: rgba(255,255,255,.025); }
                .entqra-overview-label { display:block; margin-bottom: 7px; color:#9eb9ff; font-size:11px; font-weight:800; letter-spacing:.08em; text-transform:uppercase; }
                .entqra-overview-fact p { margin:0; line-height:1.65; color:rgba(235,240,255,.86); font-size:13px; }
                .entqra-overview-fact small,.entqra-rich-item small,.entqra-timeline-item small,.entqra-product-card small { display:block; margin-top:8px; color:rgba(164,181,218,.54); font-size:10px; }
                .entqra-mini-facts { display:grid; gap:10px; }
                .entqra-mini-facts div { padding-bottom:10px; border-bottom:1px solid rgba(104,129,190,.1); }
                .entqra-mini-facts div:last-child { border-bottom:0; padding-bottom:0; }
                .entqra-mini-facts span { display:block; color:#8faeff; font-size:10px; font-weight:800; text-transform:uppercase; letter-spacing:.08em; }
                .entqra-mini-facts p { margin:4px 0 0; color:rgba(230,237,252,.8); line-height:1.5; font-size:12px; }
                .entqra-rich-list,.entqra-people-list { display:grid; gap:0; }
                .entqra-rich-item { display:grid; grid-template-columns:38px minmax(0,1fr); gap:14px; padding:15px 0; border-bottom:1px solid rgba(104,129,190,.1); }
                .entqra-rich-item:last-child { border-bottom:0; }
                .entqra-rich-index { display:grid; place-items:center; width:32px; height:32px; border-radius:9px; background:rgba(74,115,255,.12); color:#91b0ff; font-size:10px; font-weight:800; }
                .entqra-rich-item p { margin:0; color:rgba(235,240,255,.86); line-height:1.7; font-size:14px; }
                .entqra-rich-item strong { color:#f1f5ff; }
                .entqra-timeline { position:relative; display:grid; gap:0; }
                .entqra-timeline::before { content:""; position:absolute; left:16px; top:18px; bottom:18px; width:1px; background:rgba(112,143,235,.22); }
                .entqra-timeline-item { position:relative; display:grid; grid-template-columns:40px minmax(0,1fr); gap:14px; padding:15px 0; }
                .entqra-timeline-marker { z-index:1; display:grid; place-items:center; width:32px; height:32px; border-radius:50%; background:#09142d; border:1px solid rgba(115,151,255,.42); color:#9bb8ff; font-size:10px; font-weight:800; }
                .entqra-timeline-item p { margin:0; color:rgba(235,240,255,.86); line-height:1.7; font-size:14px; }
                .entqra-product-grid { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:12px; }
                .entqra-product-card { padding:16px; border:1px solid rgba(104,129,190,.12); border-radius:14px; background:rgba(255,255,255,.025); }
                .entqra-product-card > span { color:#91b0ff; font-size:10px; font-weight:800; letter-spacing:.08em; }
                .entqra-product-card p { margin:8px 0 0; line-height:1.65; color:rgba(235,240,255,.86); font-size:13px; }
                .entqra-graph-wrap { margin-top: 16px; border:1px solid rgba(104,129,190,.12); border-radius:16px; background:rgba(2,8,22,.42); overflow:hidden; }
                .entqra-graph { width:100%; min-height:360px; display:block; }
                .entqra-graph-edge { stroke:rgba(125,153,255,.35); stroke-width:1.4; }
                .entqra-graph-edge-label { fill:rgba(181,198,235,.65); font-size:9px; }
                .entqra-graph-node { fill:#0b1731; stroke:rgba(113,150,255,.48); stroke-width:1.5; }
                .entqra-graph-node-text { fill:#e6edff; font-size:10px; font-weight:750; }
                .entqra-graph-root { fill:rgba(70,95,220,.2); stroke:rgba(129,154,255,.85); stroke-width:2; }
                .entqra-graph-root-text { fill:#ffffff; font-size:12px; font-weight:850; }
                .entqra-graph-legend { display:flex; flex-wrap:wrap; gap:14px; padding:12px 15px; border-top:1px solid rgba(104,129,190,.1); color:rgba(178,193,225,.64); font-size:10px; }
                .entqra-graph-legend i { display:inline-block; vertical-align:middle; margin-right:5px; }
                .entqra-legend-root,.entqra-legend-node { width:8px; height:8px; border-radius:50%; background:#6e8dff; }
                .entqra-legend-line { width:15px; height:1px; background:#7d99ff; }
                .entqra-relationship-list { display:grid; gap:0; margin-top:15px; }
                .entqra-relationship-row { display:grid; grid-template-columns:32px minmax(0,1fr); gap:12px; padding:12px 0; border-bottom:1px solid rgba(104,129,190,.1); }
                .entqra-relationship-row > span { color:#91b0ff; font-size:10px; font-weight:800; }
                .entqra-relationship-row p { margin:0; color:rgba(230,237,252,.84); line-height:1.6; font-size:13px; }
                @media (max-width:900px) { .entqra-overview-grid,.entqra-product-grid { grid-template-columns:1fr; } }
                @media (max-width:620px) { .entqra-profile-identity { flex-direction:column; } .entqra-profile-logo-wrap { width:60px; height:60px; flex-basis:60px; } .entqra-profile-logo,.entqra-profile-logo-fallback { width:60px; height:60px; } .entqra-graph { min-height:300px; } }
                @media (max-width:700px) { .entqra-profile-hero { grid-template-columns: 1fr; } }
                @media (max-width:900px) { .entqra-research-grid { grid-template-columns: 1fr; } }
                @media (max-width:620px) {
                  .entqra-research-form { flex-direction: column; align-items: stretch; }
                  .entqra-research-form button { width: 100%; }
                  .entqra-signals { grid-template-columns: 1fr 1fr; }
                  .entqra-source-head { flex-direction: column; }
                }
              `}</style>

              <header className="discover-header">
                <p className="discover-eyebrow">ENTQRA INTELLIGENCE ENGINE</p>
                <h1>Intelligent <span>Research.</span></h1>
                <p className="discover-description">
                  Ask a question. EntQra researches the live web, weighs the evidence and organizes the result into intelligence.
                </p>
              </header>

              <form className="entqra-research-form" onSubmit={handleIntelligenceSearch}>
                <input
                  type="text"
                  value={intelligenceQuery}
                  onChange={(event) => setIntelligenceQuery(event.target.value)}
                  placeholder="Ask EntQra a question..."
                  aria-label="Ask EntQra a question"
                />
                <button type="submit" disabled={intelligenceLoading}>
                  {intelligenceLoading ? "Researching..." : "Research"}
                </button>
              </form>

              {intelligenceError && (
                <div className="entqra-research-error" role="alert">
                  {intelligenceError}
                </div>
              )}

              {intelligenceLoading && (
                <div className="entqra-empty-research">
                  <strong>EntQra is researching the web...</strong>
                  <span>Researching multiple angles, cross-checking evidence, removing duplicates and building the intelligence dossier.</span>
                </div>
              )}

              {!intelligenceLoading && !intelligenceResult && !intelligenceError && (
                <div className="entqra-empty-research">
                  <strong>Ask EntQra anything.</strong>
                  <span>Start with a company, person, technology, event or relationship you want to understand.</span>
                </div>
              )}

              {!intelligenceLoading && intelligenceResult && (() => {
                const result = intelligenceResult;
                const confidence = result.confidence;
                const confidenceRationale = typeof confidence === "object" ? confidence?.rationale : "";
                 const confidenceDisplay = formatConfidence(typeof confidence === "object" ? confidence : {});
                const findings = Array.isArray(result.key_findings) ? result.key_findings : [];
                const evidence = Array.isArray(result.evidence) ? result.evidence : [];
                const claims = Array.isArray(result.claims) ? result.claims : [];
                const sources = Array.isArray(result.sources) ? result.sources : [];
                const resultEntities = Array.isArray(result.entities) ? result.entities : [];
                const resultRelationships = Array.isArray(result.relationships) ? result.relationships : [];
                const research = result.research || {};
                const dossier = result.dossier || {};
                const profile = dossier.profile || dossier;
                const dossierSections = Array.isArray(dossier.sections)
                  ? dossier.sections
                  : Array.isArray(result.blocks)
                    ? result.blocks
                    : [];
                const overviewSection = dossierSections.find((section) => section.id === "overview");
                const relationshipSection = dossierSections.find((section) => section.id === "relationships");
                const graph = result.knowledge_graph || dossierSections.find((section) => section.id === "knowledge_graph")?.graph;
                const answer = typeof result.answer === "string" && result.answer.trim()
                  ? result.answer
                  : "EntQra completed the research but did not receive a synthesized answer.";
                const website = normalizeWebsite(profile.website || dossierSections.find((section) => section.id === "entity_header")?.data?.website);
                const logoUrl = profile.logo_url || dossierSections.find((section) => section.id === "entity_header")?.data?.logo_url || "";
                const visibleDossierSections = dossierSections.filter((section) => ![
                  "entity_header", "intelligence_answer", "key_findings", "evidence", "knowledge_graph",
                  "evidence_overview", "research_signals", "relationships", "contradictions", "evidence"
                ].includes(section.id));
                const overviewItems = Array.isArray(overviewSection?.items) ? overviewSection.items : [];
                const overviewLabels = overviewItems.map((item) => item.label || "Fact");

                return (
                  <>
                    <section className="entqra-profile-hero">
                      <div className="entqra-profile-identity">
                        <div className="entqra-profile-logo-wrap">
                          {logoUrl ? (
                            <img className="entqra-profile-logo" src={logoUrl} alt={`${profile.name || result.query || "Entity"} logo`} onError={(event) => { event.currentTarget.style.display = "none"; }} />
                          ) : null}
                          <div className="entqra-profile-logo-fallback">{String(profile.name || result.query || "E").charAt(0).toUpperCase()}</div>
                        </div>
                        <div>
                          <div className="entqra-profile-kicker">RESEARCHED ENTITY / TOPIC</div>
                          <h2 className="entqra-profile-name">{profile.name || result.query || "Research result"}</h2>
                          <div className="entqra-profile-meta">
                            <span>{profile.type || "Research topic"}</span>
                            {profile.category ? <span> • {profile.category}</span> : null}
                          </div>
                          {profile.description && <p className="entqra-profile-description">{profile.description}</p>}
                          {website && (
                            <a className="entqra-profile-website" href={website} target="_blank" rel="noopener noreferrer">
                              Visit official website ↗
                            </a>
                          )}
                        </div>
                      </div>
                      <div className="entqra-profile-badge">Source-backed</div>
                    </section>

                    <section className="entqra-answer-card">
                      <div className="entqra-section-label">
                        <span>ENTQRA INTELLIGENCE ANSWER</span>
                        <span className="entqra-confidence"><span className="entqra-confidence-dot" />{confidenceDisplay.level} · {confidenceDisplay.score}</span>
                      </div>
                      <div className="entqra-answer">{answer.split(/\n\n+/).map((paragraph, index) => <p key={`answer-${index}`}>{paragraph}</p>)}</div>
                      {confidenceRationale && <p className="entqra-confidence-rationale">{confidenceRationale}</p>}
                    </section>

                    <section className="entqra-card entqra-overview-section">
                      <div className="entqra-section-label"><span>ENTITY INTELLIGENCE</span></div>
                      <h3>Detailed Description</h3>
                      <p className="entqra-profile-description" style={{ margin: 0 }}>
                        {profile.description || "EntQra did not retrieve a sufficiently detailed source-backed description for this entity yet."}
                      </p>
                    </section>

                    <section className="entqra-card entqra-key-findings-card">
                      <div className="entqra-section-label"><span>RESEARCH SYNTHESIS</span><span>{findings.length || 0} FINDINGS</span></div>
                      <h3>Key Findings</h3>
                      <p className="entqra-section-intro">The most important conclusions from the research, organized from foundational facts to broader context.</p>
                      <div className="entqra-findings">
                        {(findings.length ? findings : claims.slice(0, 6)).map((finding, index) => {
                          const text = getItemText(finding);
                          return (
                            <article className="entqra-finding" key={`finding-${index}`}>
                              <span className="entqra-finding-number">{String(index + 1).padStart(2, "0")}</span>
                              <p className="entqra-finding-text">{text}</p>
                            </article>
                          );
                        })}
                      </div>
                    </section>

                    <div className="entqra-research-grid">
                      <section className="entqra-card">
                        <div className="entqra-section-label"><span>RESEARCH SIGNALS</span></div>
                        <h3>Evidence Overview</h3>
                        <div className="entqra-signals">
                          <div className="entqra-signal"><span>Sources analyzed</span><strong>{research.source_count ?? sources.length}</strong></div>
                          <div className="entqra-signal"><span>Independent domains</span><strong>{research.independent_domains ?? "—"}</strong></div>
                          <div className="entqra-signal"><span>Strong sources</span><strong>{research.strong_source_count ?? "—"}</strong></div>
                          <div className="entqra-signal"><span>Evidence items</span><strong>{research.evidence_count ?? evidence.length}</strong></div>
                        </div>
                        <div className="entqra-status">
                          {research.conflicts_detected ? "Potential conflicting evidence was detected. Review the cited sources before relying on the claim." : "Evidence was cross-checked across the retrieved sources."}
                        </div>
                      </section>

                      <section className="entqra-card entqra-quick-profile">
                        <div className="entqra-section-label"><span>ENTITY SNAPSHOT</span></div>
                        <h3>At a Glance</h3>
                        <div className="entqra-mini-facts">
                          {overviewItems.slice(0, 4).map((item, index) => (
                            <div key={`mini-${index}`}>
                              <span>{overviewLabels[index]}</span>
                              <p>{getItemText(item)}</p>
                            </div>
                          ))}
                        </div>
                      </section>
                    </div>

                    {overviewItems.length > 0 && (
                      <section className="entqra-dossier-section entqra-overview-section">
                        <div className="entqra-section-label"><span>ENTQRA DOSSIER</span></div>
                        <h3>Overview</h3>
                        <div className="entqra-overview-grid">
                          {overviewItems.map((item, index) => (
                            <div className="entqra-overview-fact" key={`overview-${index}`}>
                              <span className="entqra-overview-label">{item.label || "Key fact"}</span>
                              <p>{getItemText(item)}</p>
                              {(item.source_name || item.domain) && <small>{item.source_name || "Research source"}{item.domain ? ` • ${item.domain}` : ""}</small>}
                            </div>
                          ))}
                        </div>
                      </section>
                    )}

                    {visibleDossierSections.map((section) => {
                      const items = Array.isArray(section.items) ? section.items : [];
                      if (!items.length) return null;
                      return (
                        <section className={`entqra-dossier-section entqra-section-${section.id || "research"}`} key={section.id || section.title}>
                          <div className="entqra-section-label"><span>ENTQRA DOSSIER</span></div>
                          <h3>{section.title}</h3>
                          {section.question && <p className="entqra-section-question">{section.question}</p>}
                          {section.id === "people" ? (
                            <div className="entqra-people-list">
                              {items.map((item, index) => (
                                <article className="entqra-rich-item" key={`${section.id}-${index}`}>
                                  <span className="entqra-rich-index">{String(index + 1).padStart(2, "0")}</span>
                                  <div><p>{renderLeadershipText(getItemText(item))}</p><small>{item.source_name || "Research source"}{item.domain ? ` • ${item.domain}` : ""}</small></div>
                                </article>
                              ))}
                            </div>
                          ) : section.id === "history" ? (
                            <div className="entqra-timeline">
                              {items.map((item, index) => (
                                <article className="entqra-timeline-item" key={`${section.id}-${index}`}>
                                  <div className="entqra-timeline-marker">{String(index + 1).padStart(2, "0")}</div>
                                  <div><p>{getItemText(item)}</p><small>{item.source_name || "Research source"}{item.domain ? ` • ${item.domain}` : ""}</small></div>
                                </article>
                              ))}
                            </div>
                          ) : section.id === "products_services" ? (
                            <div className="entqra-product-grid">
                              {items.map((item, index) => (
                                <article className="entqra-product-card" key={`${section.id}-${index}`}>
                                  <span>{String(index + 1).padStart(2, "0")}</span>
                                  <p>{getItemText(item)}</p>
                                  <small>{item.source_name || "Research source"}{item.domain ? ` • ${item.domain}` : ""}</small>
                                </article>
                              ))}
                            </div>
                          ) : (
                            <div className="entqra-rich-list">
                              {items.map((item, index) => (
                                <article className="entqra-rich-item" key={`${section.id}-${index}`}>
                                  <span className="entqra-rich-index">{String(index + 1).padStart(2, "0")}</span>
                                  <div><p>{getItemText(item)}</p><small>{item.source_name || "Research source"}{item.domain ? ` • ${item.domain}` : ""}</small></div>
                                </article>
                              ))}
                            </div>
                          )}
                        </section>
                      );
                    })}

                    {(graph || relationshipSection || resultRelationships.length > 0) && (
                      <section className="entqra-dossier-section entqra-relationships-section">
                        <div className="entqra-section-label"><span>ENTQRA DOSSIER</span></div>
                        <h3>Relationships / Connections</h3>
                        <p className="entqra-section-question">See how the researched entity connects to companies, products, people, technologies and other organizations.</p>
                        {graph && <ResearchGraph graph={graph} subject={profile.name || result.query} />}
                        {(relationshipSection?.items?.length || resultRelationships.length) > 0 && (
                          <div className="entqra-relationship-list">
                            {(relationshipSection?.items || resultRelationships).slice(0, 10).map((item, index) => {
                              const text = getItemText(item) || `${item.source_entity_name || profile.name} ${item.relationship_type || "is related to"} ${item.target_entity_name || "another entity"}`;
                              return <div className="entqra-relationship-row" key={`rel-${index}`}><span>{String(index + 1).padStart(2, "0")}</span><p>{text}</p></div>;
                            })}
                          </div>
                        )}
                      </section>
                    )}

                    {evidence.length > 0 && (
                      <section className="entqra-card">
                        <div className="entqra-section-label"><span>VERIFIABLE EVIDENCE</span><span>{evidence.length} ITEMS</span></div>
                        <h3>Evidence</h3>
                        <div className="entqra-evidence-list">
                          {evidence.slice(0, 12).map((item, index) => (
                            <div className="entqra-evidence-item" key={`evidence-${index}`}>
                              <p>{getItemText(item)}</p>
                              <div className="entqra-evidence-meta"><span>{item?.source_name || item?.source || "Research source"}</span><span>{item?.domain || ""}</span></div>
                            </div>
                          ))}
                        </div>
                      </section>
                    )}

                    {sources.length > 0 && (
                      <section className="entqra-card">
                        <div className="entqra-section-label"><span>RESEARCH SOURCES</span><span>{sources.length} SOURCES</span></div>
                        <h3>Sources</h3>
                        <div className="entqra-source-list">
                          {sources.map((source, index) => (
                            <div className="entqra-source-item" key={source.url || `source-${index}`}>
                              <div className="entqra-source-head">
                                <div>
                                  <a className="entqra-source-title" href={source.url || "#"} target="_blank" rel="noopener noreferrer">{source.title || "Research source"}</a>
                                  <div className="entqra-source-domain">{source.domain || "Unknown domain"}</div>
                                </div>
                                <span className="entqra-source-quality">{source.quality || "source"}</span>
                              </div>
                              <p>{source.snippet || "Evidence retrieved from this source."}</p>
                              <div className="entqra-source-footer"><span>Source {index + 1}{source.search_focus ? ` • ${source.search_focus}` : ""}</span>{source.url && <a href={source.url} target="_blank" rel="noopener noreferrer">Open source ↗</a>}</div>
                            </div>
                          ))}
                        </div>
                      </section>
                    )}

                    {resultEntities.length > 0 && (
                      <section className="entqra-card">
                        <div className="entqra-section-label"><span>ENTQRA GRAPH CONTEXT</span></div>
                        <h3>Related Entities</h3>
                        <div className="entqra-entity-context">
                          {resultEntities.map((entity) => (
                            <button type="button" className="entqra-entity-chip" key={entity.id ?? entity.name} onClick={() => handleViewEntity(entity)}>
                              <strong>{entity.name || "Unknown entity"}</strong>
                              <span>{entity.entity_type || "entity"}{entity.category ? ` • ${entity.category}` : ""}</span>
                            </button>
                          ))}
                        </div>
                      </section>
                    )}
                  </>
                );
              })()}

            </div>
          )}

          {/* =================================================
              SETTINGS
              ================================================= */}

          {activeSection === "settings" && (
            <div className="discover-page">

              <header className="discover-header">

                <p className="discover-eyebrow">
                  ACCOUNT
                </p>

                <h1>
                  EntQra{" "}
                  <span>Settings.</span>
                </h1>

                <p className="discover-description">
                  Manage your EntQra account and
                  preferences.
                </p>

              </header>

              <div className="dashboard-panel">

                <div className="panel-header">

                  <div>

                    <span className="panel-label">
                      ACCOUNT INFORMATION
                    </span>

                    <h2>
                      Profile
                    </h2>

                  </div>

                </div>

                <div className="entity-list">

                  <div className="entity-row">

                    <div className="entity-avatar">
                      {currentUser.name
                        ?.charAt(0)
                        ?.toUpperCase() || "U"}
                    </div>

                    <div className="entity-info">

                      <strong>
                        {currentUser.name || "User"}
                      </strong>

                      <span>
                        {currentUser.email || ""}
                      </span>

                    </div>

                  </div>

                </div>

              </div>

            </div>
          )}

        </section>
      </main>
    );
  }

  // =========================================================
  // LOGIN PAGE
  // =========================================================

  return (
    <main className="login-page">

      {/* =====================================================
          LEFT BRAND SECTION
          ===================================================== */}

      <section className="brand-section">

        <div className="brand-content">

          <div className="brand-logo">
            ENT<span className="logo-q">Q</span>RA
          </div>

          <h1 className="brand-tagline">
            Where Information
            <br />
            Meets <span>Intelligence.</span>
          </h1>

          <div className="brand-line" />

          <p className="brand-description">
            EntQra is an AI-Powered Entity Intelligence
            &amp; Discovery Platform that helps you discover,
            verify, and understand any real-world entity
            with trusted information and intelligent insights.
          </p>

          <div className="feature-grid">

            <div className="feature feature-shield">

              <div className="feature-icon">

                <svg
                  viewBox="0 0 32 32"
                  aria-hidden="true"
                >
                  <path d="M16 3L27 7V15C27 22 22.5 27 16 29C9.5 27 5 22 5 15V7L16 3Z" />

                  <path d="M10.5 16L14 19.5L21.5 12" />
                </svg>

              </div>

              <div className="feature-copy">

                <strong>
                  Verified Information.
                </strong>

                <span>
                  First. AI Second.
                </span>

              </div>

            </div>

            <div className="feature feature-target">

              <div className="feature-icon">

                <svg
                  viewBox="0 0 32 32"
                  aria-hidden="true"
                >
                  <circle
                    cx="16"
                    cy="16"
                    r="11"
                  />

                  <circle
                    cx="16"
                    cy="16"
                    r="5"
                  />

                  <path d="M16 2V7M16 25V30M2 16H7M25 16H30" />
                </svg>

              </div>

              <div className="feature-copy">

                <strong>
                  Multiple Sources.
                </strong>

                <span>
                  Cross Verification.
                </span>

              </div>

            </div>

            <div className="feature feature-user">

              <div className="feature-icon">

                <svg
                  viewBox="0 0 32 32"
                  aria-hidden="true"
                >
                  <circle
                    cx="16"
                    cy="10"
                    r="5"
                  />

                  <path d="M6 28C6 22 10 18 16 18C22 18 26 22 26 28" />
                </svg>

              </div>

              <div className="feature-copy">

                <strong>
                  User First.
                </strong>

                <span>
                  Always Relevant.
                </span>

              </div>

            </div>

            <div className="feature feature-insight">

              <div className="feature-icon">

                <svg
                  viewBox="0 0 32 32"
                  aria-hidden="true"
                >
                  <path d="M6 27V19" />
                  <path d="M13 27V13" />
                  <path d="M20 27V8" />
                  <path d="M27 27V4" />

                  <circle
                    cx="6"
                    cy="17"
                    r="2"
                  />

                  <circle
                    cx="13"
                    cy="11"
                    r="2"
                  />

                  <circle
                    cx="20"
                    cy="6"
                    r="2"
                  />

                  <circle
                    cx="27"
                    cy="2.5"
                    r="2"
                  />
                </svg>

              </div>

              <div className="feature-copy">

                <strong>
                  Intelligent Insights
                </strong>

                <span>
                  Always Updated.
                </span>

              </div>

            </div>

          </div>

        </div>

        {/* NETWORK GLOBE */}

        <div
          className="network-globe"
          aria-hidden="true"
        >

          <div className="globe-ring ring-one" />
          <div className="globe-ring ring-two" />
          <div className="globe-ring ring-three" />

          <div className="node node-1" />
          <div className="node node-2" />
          <div className="node node-3" />
          <div className="node node-4" />
          <div className="node node-5" />
          <div className="node node-6" />
          <div className="node node-7" />
          <div className="node node-8" />
          <div className="node node-9" />

          <div className="globe-line line-one" />
          <div className="globe-line line-two" />
          <div className="globe-line line-three" />
          <div className="globe-line line-four" />
          <div className="globe-line line-five" />

        </div>

      </section>

      {/* =====================================================
          RIGHT LOGIN SECTION
          ===================================================== */}

      <section className="login-section">

        <div className="login-card">

          {/* LOCK */}

          <div className="lock-container">

            <div className="lock-glow" />

            <svg
              viewBox="0 0 32 32"
              aria-hidden="true"
            >
              <rect
                x="7"
                y="14"
                width="18"
                height="14"
                rx="3"
              />

              <path d="M11 14V10C11 7.2 13.2 5 16 5C18.8 5 21 7.2 21 10V14" />

              <circle
                cx="16"
                cy="21"
                r="1.5"
              />

              <path d="M16 22.5V25" />
            </svg>

          </div>

          <h2>
            Welcome Back
          </h2>

          <p className="login-subtitle">
            Sign in to continue to your EntQra account.
          </p>

          {/* LOGIN FORM */}

          <form onSubmit={handleSubmit}>

            {/* EMAIL */}

            <div className="input-group">

              <label htmlFor="email">
                Email Address
              </label>

              <div className="input-wrapper">

                <svg
                  viewBox="0 0 32 32"
                  aria-hidden="true"
                >
                  <rect
                    x="4"
                    y="7"
                    width="24"
                    height="18"
                    rx="2"
                  />

                  <path d="M5 9L16 18L27 9" />
                </svg>

                <input
                  id="email"
                  type="email"
                  value={email}
                  onChange={(event) => {
                    setEmail(event.target.value);
                    setErrorMessage("");
                  }}
                  placeholder="Email Address"
                  autoComplete="email"
                  disabled={loading}
                  required
                />

              </div>

            </div>

            {/* PASSWORD */}

            <div className="input-group">

              <label htmlFor="password">
                Password
              </label>

              <div className="input-wrapper">

                <svg
                  viewBox="0 0 32 32"
                  aria-hidden="true"
                >
                  <rect
                    x="7"
                    y="14"
                    width="18"
                    height="14"
                    rx="3"
                  />

                  <path d="M11 14V10C11 7.2 13.2 5 16 5C18.8 5 21 7.2 21 10V14" />

                  <circle
                    cx="16"
                    cy="21"
                    r="1.5"
                  />
                </svg>

                <input
                  id="password"
                  type={
                    showPassword
                      ? "text"
                      : "password"
                  }
                  value={password}
                  onChange={(event) => {
                    setPassword(event.target.value);
                    setErrorMessage("");
                  }}
                  placeholder="Password"
                  autoComplete="current-password"
                  disabled={loading}
                  required
                />

                <button
                  type="button"
                  className="password-toggle"
                  onClick={() =>
                    setShowPassword(
                      (value) => !value
                    )
                  }
                  aria-label={
                    showPassword
                      ? "Hide password"
                      : "Show password"
                  }
                  disabled={loading}
                >

                  {showPassword ? (

                    <svg
                      viewBox="0 0 32 32"
                      aria-hidden="true"
                    >
                      <path d="M4 4L28 28" />

                      <path d="M13.5 13.5C12.8 14.2 12.5 15 12.5 16C12.5 18 14 19.5 16 19.5C17 19.5 17.8 19.2 18.5 18.5" />

                      <path d="M9.5 9.5C6.2 11.4 4.2 14.1 3 16C5.5 19.8 9.7 23 16 23C18.7 23 21 22.3 23 21" />

                      <path d="M13 6.5C14 6.2 15 6 16 6C22.3 6 26.5 9.2 29 13C28.3 14.1 27.2 15.5 26 16.8" />
                    </svg>

                  ) : (

                    <svg
                      viewBox="0 0 32 32"
                      aria-hidden="true"
                    >
                      <path d="M3 16C5.5 11.5 10 7 16 7C22 7 26.5 11.5 29 16C26.5 20.5 22 25 16 25C10 25 5.5 20.5 3 16Z" />

                      <circle
                        cx="16"
                        cy="16"
                        r="4"
                      />
                    </svg>

                  )}

                </button>

              </div>

            </div>

            {/* OPTIONS */}

            <div className="login-options">

              <label className="remember">

                <input
                  type="checkbox"
                  checked={rememberMe}
                  onChange={(event) =>
                    setRememberMe(
                      event.target.checked
                    )
                  }
                  disabled={loading}
                />

                <span className="custom-checkbox" />

                <span>
                  Remember Me
                </span>

              </label>

              <button
                type="button"
                className="forgot-password"
                onClick={handleForgotPassword}
                disabled={loading}
              >
                Forgot Password?
              </button>

            </div>

            {/* ERROR */}

            {errorMessage && (
              <div
                className="login-message error-message"
                role="alert"
              >
                {errorMessage}
              </div>
            )}

            {/* SUCCESS */}

            {successMessage && (
              <div
                className="login-message success-message"
                role="status"
              >
                {successMessage}
              </div>
            )}

            {/* SIGN IN */}

            <button
              type="submit"
              className="signin-button"
              disabled={loading}
            >

              <span>
                {loading
                  ? "Signing In..."
                  : "Sign In"}
              </span>

              {!loading && (
                <svg
                  viewBox="0 0 32 32"
                  aria-hidden="true"
                >
                  <path d="M5 16H26" />
                  <path d="M18 8L26 16L18 24" />
                </svg>
              )}

            </button>

          </form>

          {/* DIVIDER */}

          <div className="divider">

            <span />
            <p>OR</p>
            <span />

          </div>

          {/* GOOGLE */}

          <button
            type="button"
            className="google-button"
            onClick={handleGoogleLogin}
            disabled={loading}
          >

            <svg
              viewBox="0 0 24 24"
              aria-hidden="true"
            >

              <path
                fill="#4285F4"
                d="M23.49 12.27C23.49 11.48 23.42 10.73 23.28 10H12V14.26H18.44C18.16 15.63 17.38 16.79 16.16 17.57V20.39H19.73C21.82 18.47 23.49 15.65 23.49 12.27Z"
              />

              <path
                fill="#34A853"
                d="M12 24C15 24 17.52 23.01 19.73 21.32L16.16 18.5C15.17 19.16 13.93 19.56 12 19.56C9.12 19.56 6.68 17.61 5.81 15H2.12V17.91C4.32 21.51 7.9 24 12 24Z"
              />

              <path
                fill="#FBBC05"
                d="M5.81 15C5.59 14.34 5.46 13.63 5.46 12.9C5.46 12.17 5.59 11.46 5.81 10.8V7.89H2.12C1.36 9.41 0.92 11.12 0.92 12.9C0.92 14.68 1.36 16.39 2.12 17.91L5.81 15Z"
              />

              <path
                fill="#EA4335"
                d="M12 4.56C13.63 4.56 15.09 5.12 16.25 6.22L19.81 2.66C17.52 0.88 15 0 12 0C7.9 0 4.32 2.49 2.12 6.09L5.81 9C6.68 6.39 9.12 4.56 12 4.56Z"
              />

            </svg>

            <span>
              Sign in with Google
            </span>

          </button>

          {/* REGISTER */}

          <p className="register-text">

            New to EntQra?

            <button
              type="button"
              onClick={handleCreateAccount}
              disabled={loading}
            >
              Create an account
            </button>

          </p>

        </div>

        {/* SECURITY */}

        <div className="security-message">

          <svg
            viewBox="0 0 32 32"
            aria-hidden="true"
          >
            <path d="M16 3L27 7V15C27 22 22.5 27 16 29C9.5 27 5 22 5 15V7L16 3Z" />

            <path d="M11 16L14.5 19.5L21.5 12.5" />
          </svg>

          <span>
            Your data is secure with enterprise-grade encryption
          </span>

        </div>

      </section>

    </main>
  );
}

export default App;