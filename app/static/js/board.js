/* The board: rendering, filtering, drag & drop, and the project drawer. */
(function () {
  "use strict";
  const { api, toast, escapeHtml, formatDate } = window.CB;

  const boardEl = document.getElementById("board");
  const drawerEl = document.getElementById("drawer");
  const scrimEl = document.getElementById("scrim");
  const modalEl = document.getElementById("project-modal");
  const formEl = document.getElementById("project-form");
  const f = formEl.elements;
  const FILES = "abcdefghijklmnop";

  const PIECES = JSON.parse(document.getElementById("piece-meta").textContent);
  const STATUSES = JSON.parse(document.getElementById("status-meta").textContent);
  const initial = JSON.parse(document.getElementById("initial-data").textContent);

  const state = {
    board: initial.board,
    projects: initial.projects,
    people: initial.people,
    filter: { status: "all", person: "all", query: "" },
    openProjectId: null,
  };
  let drag = null;

  const byId = (id) => state.projects.find((p) => p.id === id);
  const at = (x, y) => state.projects.find((p) => p.pos_x === x && p.pos_y === y);

  function matchesFilter(project) {
    const f = state.filter;
    if (f.status !== "all" && project.status !== f.status) return false;
    if (f.person !== "all" && !project.members.some((m) => m.user_id === f.person)) return false;
    if (f.query) {
      const haystack = [project.name, project.description || "", (project.tags || []).join(" "),
        project.members.map((m) => m.name).join(" ")].join(" ").toLowerCase();
      if (!haystack.includes(f.query)) return false;
    }
    return true;
  }

  // ------------------------------------------------------------ rendering ---
  function pieceHtml(member) {
    const meta = PIECES[member.piece] || PIECES.pawn;
    return `<span class="piece" draggable="true" data-assignment="${member.id}"
      style="--piece: ${meta.color}" title="${escapeHtml(member.name)} — ${escapeHtml(meta.role)}"
      role="img" aria-label="${escapeHtml(member.name)}, ${escapeHtml(meta.role)}">${meta.glyph}</span>`;
  }

  function squareHtml(project, x, y) {
    if (!project) {
      return `<button class="square is-empty ${(x + y) % 2 ? "dark" : ""}" data-x="${x}" data-y="${y}"
        aria-label="Empty square ${FILES[x]}${state.board.rows - y}. Create a project here."></button>`;
    }
    const status = STATUSES[project.status] || STATUSES.planning;
    const dim = matchesFilter(project) ? "" : "is-dim";
    const selected = state.openProjectId === project.id ? "is-selected" : "";
    return `<button class="square ${(x + y) % 2 ? "dark" : ""} ${dim} ${selected}" data-x="${x}" data-y="${y}"
      data-project="${project.id}" draggable="true" style="--status: ${status.color}"
      aria-label="${escapeHtml(project.name)}, ${escapeHtml(status.label)}, ${project.progress}% complete, ${project.members.length} people">
      <span class="square-status"></span><span class="square-stripe"></span>
      <span class="square-name">${escapeHtml(project.name)}</span>
      <span class="square-pieces">${project.members.map(pieceHtml).join("")}</span>
      <span class="square-progress"><i style="width: ${project.progress}%"></i></span>
    </button>`;
  }

  function render() {
    const { rows, cols } = state.board;
    boardEl.style.gridTemplateColumns = `repeat(${cols}, minmax(0, 1fr))`;
    const squares = [];
    for (let y = 0; y < rows; y += 1) {
      for (let x = 0; x < cols; x += 1) squares.push(squareHtml(at(x, y), x, y));
    }
    boardEl.innerHTML = squares.join("");

    const ranks = document.getElementById("rank-labels");
    ranks.style.gridTemplateRows = `repeat(${rows}, minmax(0, 1fr))`;
    ranks.innerHTML = Array.from({ length: rows }, (_, i) => `<span>${rows - i}</span>`).join("");
    const files = document.getElementById("file-labels");
    files.style.gridTemplateColumns = `repeat(${cols}, minmax(0, 1fr))`;
    files.innerHTML = Array.from({ length: cols }, (_, i) => `<span>${FILES[i]}</span>`).join("");

    renderRoster();
  }

  function renderRoster() {
    const counts = new Map();
    state.projects.forEach((project) => {
      if (["completed", "on_hold"].includes(project.status)) return;
      project.members.forEach((m) => counts.set(m.user_id, (counts.get(m.user_id) || 0) + 1));
    });
    const roster = document.getElementById("roster");
    roster.innerHTML = state.people.map((person) => {
      const count = counts.get(person.id) || 0;
      return `<li draggable="true" data-person="${person.id}" title="Drag onto a square to assign">
        <span class="glyph">♟</span>
        <span class="name">${escapeHtml(person.name)}</span>
        <span class="count ${count > 3 ? "warn" : ""}">${count} project${count === 1 ? "" : "s"}</span>
      </li>`;
    }).join("") || '<li class="muted">No one on this board yet.</li>';

    const select = document.getElementById("person-filter");
    const current = select.value;
    select.innerHTML = '<option value="all">Everyone</option>' +
      state.people.map((p) => `<option value="${p.id}">${escapeHtml(p.name)}</option>`).join("");
    select.value = state.people.some((p) => p.id === current) ? current : "all";
  }

  // -------------------------------------------------------------- drawer ---
  async function openDrawer(projectId) {
    state.openProjectId = projectId;
    drawerEl.hidden = false;
    scrimEl.hidden = false;
    drawerEl.innerHTML = '<p class="muted">Loading…</p>';
    try {
      const data = await api("/api/projects/" + projectId);
      renderDrawer(data);
      render();
    } catch (err) {
      toast(err.message, true);
      closeDrawer();
    }
  }

  function closeDrawer() {
    state.openProjectId = null;
    drawerEl.hidden = true;
    scrimEl.hidden = true;
    drawerEl.innerHTML = "";
    render();
  }

  function renderDrawer(data) {
    const p = data.project;
    const status = STATUSES[p.status] || STATUSES.planning;
    const unassigned = data.people.filter((person) => !p.members.some((m) => m.user_id === person.id));
    drawerEl.innerHTML = `
      <div class="drawer-head">
        <h2>${escapeHtml(p.name)}</h2>
        <button class="icon-btn" data-drawer-close aria-label="Close">✕</button>
      </div>
      <p class="muted">${escapeHtml(p.description || "No description yet.")}</p>
      <p><span class="pill" style="--pill: ${status.color}">${status.label}</span>
         <span class="muted small">${FILES[p.pos_x]}${state.board.rows - p.pos_y}</span></p>

      <section>
        <h2>Status &amp; progress</h2>
        <label class="field"><span>Status</span>
          <select data-field="status">
            ${Object.entries(STATUSES).map(([key, meta]) =>
              `<option value="${key}" ${key === p.status ? "selected" : ""}>${meta.label}</option>`).join("")}
          </select>
        </label>
        <label class="field"><span>Progress: <output id="progress-out">${p.progress}%</output></span>
          <input type="range" min="0" max="100" step="5" value="${p.progress}" data-field="progress">
        </label>
        <p class="muted small">Start ${formatDate(p.start_date)} · Deadline ${formatDate(p.deadline)}</p>
        ${(p.tags || []).length ? `<p>${p.tags.map((t) => `<span class="pill">${escapeHtml(t)}</span>`).join(" ")}</p>` : ""}
      </section>

      <section>
        <h2>Team (${p.members.length})</h2>
        ${p.members.map((m) => `
          <div class="member-row" data-assignment="${m.id}">
            <span class="glyph" style="color: ${(PIECES[m.piece] || PIECES.pawn).color}">${m.glyph}</span>
            <span class="name">${escapeHtml(m.name)}</span>
            <select data-piece-for="${m.id}" aria-label="Role for ${escapeHtml(m.name)}">
              ${Object.entries(PIECES).map(([key, meta]) =>
                `<option value="${key}" ${key === m.piece ? "selected" : ""}>${meta.glyph} ${meta.role}</option>`).join("")}
            </select>
            <button class="icon-btn" data-remove-member="${m.id}" aria-label="Remove ${escapeHtml(m.name)}">✕</button>
          </div>`).join("") || '<p class="muted small">Nobody assigned. Drag a piece here from the team list.</p>'}
        ${unassigned.length ? `
        <form class="inline-form" data-add-member style="margin-top:.5rem">
          <select name="user_id" aria-label="Person to add">
            ${unassigned.map((person) => `<option value="${person.id}">${escapeHtml(person.name)}</option>`).join("")}
          </select>
          <select name="piece" aria-label="Role">
            ${Object.entries(PIECES).map(([key, meta]) => `<option value="${key}">${meta.glyph} ${meta.role}</option>`).join("")}
          </select>
          <button class="btn btn-ghost" type="submit">Add</button>
        </form>` : ""}
      </section>

      ${data.dependencies.length ? `<section><h2>Depends on</h2>
        ${data.dependencies.map((d) => `<p>${escapeHtml(d.name)} <span class="muted small">${d.progress}%</span></p>`).join("")}
      </section>` : ""}

      <section>
        <h2>Comments</h2>
        <form class="inline-form" data-add-comment>
          <input name="body" placeholder="Add a comment…" maxlength="4000" required>
          <button class="btn btn-ghost" type="submit">Post</button>
        </form>
        <div style="margin-top:.75rem">
          ${data.comments.map((c) => `<div class="comment">
            <div class="meta">${escapeHtml(c.author)} · ${formatDate(c.created_at)}</div>
            <div>${escapeHtml(c.body)}</div></div>`).join("") || '<p class="muted small">No comments yet.</p>'}
        </div>
      </section>

      <section>
        <button class="btn btn-ghost" data-edit-project>Edit details</button>
        <button class="btn btn-ghost btn-danger" data-delete-project>Delete project</button>
      </section>`;
  }

  // --------------------------------------------------------------- edits ---
  async function patchProject(projectId, payload) {
    const updated = await api("/api/projects/" + projectId, { method: "PATCH", body: payload });
    const index = state.projects.findIndex((p) => p.id === projectId);
    if (index >= 0) state.projects[index] = Object.assign({}, state.projects[index], updated);
    render();
    return updated;
  }

  async function reload() {
    const data = await api("/api/boards/" + state.board.id);
    state.board = data.board;
    state.projects = data.projects;
    state.people = data.people;
    render();
  }

  function openProjectModal(project, square) {
    formEl.reset();
    document.getElementById("project-error").hidden = true;
    document.getElementById("project-modal-title").textContent = project ? "Edit project" : "New project";
    f.project_id.value = project ? project.id : "";
    f.pos_x.value = project ? project.pos_x : square.x;
    f.pos_y.value = project ? project.pos_y : square.y;
    if (project) {
      f.name.value = project.name;
      f.description.value = project.description || "";
      f.status.value = project.status;
      f.progress.value = project.progress;
      f.start_date.value = project.start_date || "";
      f.deadline.value = project.deadline || "";
      f.tags.value = (project.tags || []).join(", ");
    }
    modalEl.showModal();
    f.name.focus();
  }

  formEl.addEventListener("submit", async (event) => {
    event.preventDefault();
    const errorEl = document.getElementById("project-error");
    errorEl.hidden = true;
    const payload = {
      name: f.name.value.trim(),
      description: f.description.value.trim() || null,
      status: f.status.value,
      progress: Number(f.progress.value || 0),
      start_date: f.start_date.value || null,
      deadline: f.deadline.value || null,
      tags: f.tags.value.split(",").map((t) => t.trim()).filter(Boolean),
    };
    try {
      if (f.project_id.value) {
        await patchProject(f.project_id.value, payload);
      } else {
        payload.pos_x = Number(f.pos_x.value);
        payload.pos_y = Number(f.pos_y.value);
        const project = await api(`/api/boards/${state.board.id}/projects`, { method: "POST", body: payload });
        state.projects.push(Object.assign({ members: [] }, project));
        render();
      }
      modalEl.close();
      toast("Saved");
    } catch (err) {
      errorEl.textContent = err.message;
      errorEl.hidden = false;
    }
  });

  modalEl.addEventListener("click", (event) => {
    if (event.target.closest("[data-close]")) modalEl.close();
  });

  // ---------------------------------------------------------------- drag ---
  boardEl.addEventListener("dragstart", (event) => {
    const piece = event.target.closest(".piece");
    if (piece) {
      drag = { kind: "assignment", assignmentId: piece.dataset.assignment, fromProjectId: piece.closest(".square").dataset.project };
      piece.classList.add("is-dragging");
    } else {
      const square = event.target.closest(".square[data-project]");
      if (!square) return;
      drag = { kind: "project", projectId: square.dataset.project };
    }
    event.dataTransfer.effectAllowed = "move";
    event.dataTransfer.setData("text/plain", drag.kind);
  });

  boardEl.addEventListener("dragend", () => {
    drag = null;
    boardEl.querySelectorAll(".is-dragging, .is-drop").forEach((el) => el.classList.remove("is-dragging", "is-drop"));
  });

  document.getElementById("roster").addEventListener("dragstart", (event) => {
    const item = event.target.closest("[data-person]");
    if (!item) return;
    drag = { kind: "person", personId: item.dataset.person };
    event.dataTransfer.effectAllowed = "copy";
    event.dataTransfer.setData("text/plain", "person");
  });

  boardEl.addEventListener("dragover", (event) => {
    const square = event.target.closest(".square");
    if (!drag || !square) return;
    const isEmpty = !square.dataset.project;
    if (drag.kind === "project" ? isEmpty : !isEmpty) {
      event.preventDefault();
      boardEl.querySelectorAll(".is-drop").forEach((el) => el.classList.remove("is-drop"));
      square.classList.add("is-drop");
    }
  });

  boardEl.addEventListener("drop", async (event) => {
    const square = event.target.closest(".square");
    if (!drag || !square) return;
    event.preventDefault();
    square.classList.remove("is-drop");
    const payload = drag;
    drag = null;
    try {
      if (payload.kind === "project" && !square.dataset.project) {
        await patchProject(payload.projectId, { pos_x: Number(square.dataset.x), pos_y: Number(square.dataset.y) });
        toast("Project moved");
      } else if (payload.kind === "person" && square.dataset.project) {
        await api(`/api/projects/${square.dataset.project}/members`, {
          method: "POST", body: { user_id: payload.personId, piece: "pawn" },
        });
        await reload();
        toast("Assigned");
      } else if (payload.kind === "assignment" && square.dataset.project) {
        if (square.dataset.project === payload.fromProjectId) return;
        await api(`/api/projects/${payload.fromProjectId}/members/${payload.assignmentId}/move`, {
          method: "POST", body: { to_project_id: square.dataset.project },
        });
        await reload();
        toast("Piece moved");
      }
    } catch (err) {
      toast(err.message, true);
      await reload();
    }
  });

  // -------------------------------------------------------------- events ---
  boardEl.addEventListener("click", (event) => {
    const square = event.target.closest(".square");
    if (!square) return;
    if (square.dataset.project) openDrawer(square.dataset.project);
    else openProjectModal(null, { x: Number(square.dataset.x), y: Number(square.dataset.y) });
  });

  scrimEl.addEventListener("click", closeDrawer);
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && !drawerEl.hidden) closeDrawer();
  });

  drawerEl.addEventListener("click", async (event) => {
    const projectId = state.openProjectId;
    if (event.target.closest("[data-drawer-close]")) return closeDrawer();
    if (event.target.closest("[data-edit-project]")) return openProjectModal(byId(projectId), null);
    if (event.target.closest("[data-delete-project]")) {
      if (!window.confirm("Delete this project and all of its assignments?")) return;
      try {
        await api("/api/projects/" + projectId, { method: "DELETE" });
        state.projects = state.projects.filter((p) => p.id !== projectId);
        closeDrawer();
        toast("Project deleted");
      } catch (err) { toast(err.message, true); }
      return;
    }
    const remove = event.target.closest("[data-remove-member]");
    if (remove) {
      try {
        await api(`/api/projects/${projectId}/members/${remove.dataset.removeMember}`, { method: "DELETE" });
        await reload();
        await openDrawer(projectId);
      } catch (err) { toast(err.message, true); }
    }
  });

  drawerEl.addEventListener("input", (event) => {
    if (event.target.dataset.field === "progress") {
      document.getElementById("progress-out").textContent = event.target.value + "%";
    }
  });

  drawerEl.addEventListener("change", async (event) => {
    const projectId = state.openProjectId;
    const field = event.target.dataset.field;
    try {
      if (field === "status") {
        await patchProject(projectId, { status: event.target.value });
        await openDrawer(projectId);
        toast("Status updated");
      } else if (field === "progress") {
        await patchProject(projectId, { progress: Number(event.target.value) });
        toast("Progress updated");
      } else if (event.target.dataset.pieceFor) {
        await api(`/api/projects/${projectId}/members/${event.target.dataset.pieceFor}`, {
          method: "PATCH", body: { piece: event.target.value },
        });
        await reload();
        await openDrawer(projectId);
        toast("Role updated");
      }
    } catch (err) {
      toast(err.message, true);
      await openDrawer(projectId);
    }
  });

  drawerEl.addEventListener("submit", async (event) => {
    event.preventDefault();
    const projectId = state.openProjectId;
    const form = event.target;
    try {
      if (form.matches("[data-add-member]")) {
        await api(`/api/projects/${projectId}/members`, {
          method: "POST", body: { user_id: form.user_id.value, piece: form.piece.value },
        });
      } else if (form.matches("[data-add-comment]")) {
        await api(`/api/projects/${projectId}/comments`, { method: "POST", body: { body: form.body.value } });
      }
      await reload();
      await openDrawer(projectId);
    } catch (err) {
      toast(err.message, true);
    }
  });

  // ------------------------------------------------------------- filters ---
  document.getElementById("status-filters").addEventListener("click", (event) => {
    const chip = event.target.closest(".chip");
    if (!chip) return;
    state.filter.status = chip.dataset.status;
    document.querySelectorAll("#status-filters .chip").forEach((c) => c.classList.toggle("is-active", c === chip));
    render();
  });

  let searchTimer = null;
  document.getElementById("search").addEventListener("input", (event) => {
    clearTimeout(searchTimer);
    const value = event.target.value.trim().toLowerCase();
    searchTimer = setTimeout(() => { state.filter.query = value; render(); }, 150);
  });

  document.getElementById("person-filter").addEventListener("change", (event) => {
    state.filter.person = event.target.value;
    render();
  });

  document.getElementById("new-project").addEventListener("click", () => {
    const { rows, cols } = state.board;
    for (let y = 0; y < rows; y += 1) {
      for (let x = 0; x < cols; x += 1) {
        if (!at(x, y)) return openProjectModal(null, { x, y });
      }
    }
    toast("The board is full — remove a project or make the board larger.", true);
  });

  document.getElementById("add-person-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const form = event.target;
    try {
      await api(`/api/boards/${state.board.id}/people`, {
        method: "POST", body: { email: form.email.value.trim(), role: "member" },
      });
      form.reset();
      await reload();
      toast("Added to the board");
    } catch (err) {
      toast(err.message, true);
    }
  });

  // Deep link from analytics / my-work: /boards/:id?project=:id
  const requested = new URLSearchParams(window.location.search).get("project");
  render();
  if (requested) openDrawer(requested);
})();
