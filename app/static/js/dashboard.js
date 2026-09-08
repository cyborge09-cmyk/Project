/* Create a board from the dashboard. */
(function () {
  "use strict";
  const { api, toast } = window.CB;

  async function createBoard() {
    const name = window.prompt("Board name", "Engineering portfolio");
    if (!name) return;
    const size = parseInt(window.prompt("Grid size (2-16 squares per side)", "8"), 10);
    if (!size || size < 2 || size > 16) {
      toast("Grid size must be between 2 and 16", true);
      return;
    }
    try {
      const board = await api("/api/boards", { method: "POST", body: { name: name.trim(), rows: size, cols: size } });
      window.location.href = "/boards/" + board.id;
    } catch (err) {
      toast(err.message, true);
    }
  }

  ["new-board", "new-board-empty"].forEach((id) => {
    const button = document.getElementById(id);
    if (button) button.addEventListener("click", createBoard);
  });
})();
