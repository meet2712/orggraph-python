// The Python app renders the data and chart. These controls only change the view.
const companySearch = document.querySelector("#company-search");

if (companySearch) {
  const companyLinks = [...document.querySelectorAll("[data-company-search]")];
  const companyCount = document.querySelector("#company-result-count");
  const noCompanies = document.querySelector("#no-companies");
  const companyList = document.querySelector("#company-list");

  companySearch.addEventListener("input", () => {
    const query = companySearch.value.trim().toLowerCase();
    let matches = 0;

    for (const link of companyLinks) {
      link.hidden = !link.dataset.companySearch.includes(query);
      if (!link.hidden) matches += 1;
    }

    companyCount.textContent = `${matches} ${matches === 1 ? "company" : "companies"}`;
    noCompanies.hidden = matches > 0;
  });

  const selected = companyList.querySelector('[aria-current="page"]');
  if (selected) companyList.scrollTop = selected.offsetTop - companyList.offsetTop - 30;
}

const chartView = document.querySelector("#chart-view");

if (chartView) {
  const reviewView = document.querySelector("#review-view");
  const viewButtons = [...document.querySelectorAll("[data-view]")];
  const department = document.querySelector("#department-filter");
  const peopleSearch = document.querySelector("#people-search");
  const groupFilter = document.querySelector("#group-filter");
  const groupToolbar = document.querySelector("#group-toolbar");
  const groups = [...chartView.querySelectorAll(".reporting-group")];
  const nodes = [...chartView.querySelectorAll(".tree-node")];
  const reviewRows = [...reviewView.querySelectorAll("[data-review-person]")];
  const branches = [...chartView.querySelectorAll("details.branch")];
  const expandButton = document.querySelector("#expand-teams");
  const emptyMessage = document.querySelector("#no-people");
  const resultCount = document.querySelector("#people-result-count");
  const explanation = document.querySelector("#chart-explanation");
  const canvas = document.querySelector("#chart-canvas");
  const scaleBox = document.querySelector("#chart-scale");
  const canvasControls = document.querySelector("#canvas-controls");
  const zoomLevel = document.querySelector("#zoom-level");
  const zoomOut = document.querySelector("#zoom-out");
  const zoomIn = document.querySelector("#zoom-in");
  const originalCount = resultCount.textContent;
  let view = "chart";
  let zoom = 1;
  let layoutFrame = 0;
  let centerPending = false;

  if (!groupFilter.querySelector("option[selected]") && groups.length) {
    groupFilter.value = groups[0].dataset.rootId;
  }

  function matchesFilters(row) {
    const query = peopleSearch.value.trim().toLowerCase();
    return (!department.value || row.dataset.department === department.value)
      && row.dataset.search.includes(query);
  }

  function updateCanvasSize() {
    if (chartView.hidden) return;
    canvas.style.transform = `scale(${zoom})`;
    scaleBox.style.width = `${Math.ceil(canvas.offsetWidth * zoom)}px`;
    scaleBox.style.height = `${Math.ceil(canvas.offsetHeight * zoom)}px`;
    zoomLevel.textContent = `${Math.round(zoom * 100)}%`;
    zoomOut.disabled = zoom <= 0.4;
    zoomIn.disabled = zoom >= 1.5;
  }

  function requestLayout(center = false) {
    centerPending ||= center;
    if (layoutFrame) return;
    layoutFrame = requestAnimationFrame(() => {
      layoutFrame = 0;
      updateCanvasSize();
      if (centerPending && !chartView.hidden) {
        chartView.scrollLeft = Math.max(0, (scaleBox.offsetWidth - chartView.clientWidth) / 2);
        chartView.scrollTop = 0;
      }
      centerPending = false;
    });
  }

  function setZoom(value, keepPosition = true) {
    const centerX = (chartView.scrollLeft + chartView.clientWidth / 2) / zoom;
    const centerY = (chartView.scrollTop + chartView.clientHeight / 2) / zoom;
    zoom = Math.min(1.5, Math.max(0.4, value));
    updateCanvasSize();
    if (keepPosition) {
      chartView.scrollLeft = centerX * zoom - chartView.clientWidth / 2;
      chartView.scrollTop = centerY * zoom - chartView.clientHeight / 2;
    }
  }

  function fitChart() {
    if (chartView.hidden) return;
    const visibleGroups = groups.filter((group) => !group.hidden).length;
    const widthScale = (chartView.clientWidth - 24) / canvas.offsetWidth;
    const heightScale = visibleGroups === 1
      ? (chartView.clientHeight - 24) / canvas.offsetHeight : 1;
    setZoom(Math.min(1, widthScale, heightScale), false);
    requestLayout(true);
  }

  function updateExpandButton() {
    const visibleBranches = branches.filter((branch) => !branch.closest(".reporting-group").hidden
      && !branch.closest(".tree-node").hidden);
    const allOpen = visibleBranches.length > 0 && visibleBranches.every((branch) => branch.open);
    expandButton.textContent = allOpen ? "Collapse all" : "Expand all";
    expandButton.disabled = visibleBranches.length === 0;
    requestLayout();
  }

  function updateConnectors() {
    for (const row of canvas.querySelectorAll(".tree-children")) {
      const visible = [...row.children].filter((node) => !node.hidden);
      for (const node of row.children) {
        node.classList.toggle("first", node === visible[0]);
        node.classList.toggle("last", node === visible.at(-1));
      }
      row.classList.toggle("no-visible-reports", visible.length === 0);
    }
  }

  function updatePeople(center = true) {
    const matchingNodes = new Set(nodes.filter((node) => matchesFilters(node)
      && (!groupFilter.value || node.closest(".reporting-group").dataset.rootId === groupFilter.value)));
    const filtered = Boolean(department.value || peopleSearch.value.trim());

    // Keep real ancestors of every match. A filter never creates a reporting line.
    for (const node of nodes) node.hidden = true;
    for (const match of matchingNodes) {
      let current = match;
      while (current) {
        current.hidden = false;
        const parent = current.parentElement.closest(".tree-node");
        if (filtered && parent) parent.querySelector("details.branch").open = true;
        current = parent;
      }
    }
    for (const node of nodes) {
      node.dataset.context = filtered && !matchingNodes.has(node) ? "true" : "false";
    }
    for (const group of groups) {
      group.hidden = !group.querySelector(".tree-node:not([hidden])");
    }
    updateConnectors();

    let reviewMatches = 0;
    let peopleMatches = 0;
    for (const row of reviewRows) {
      const matches = matchesFilters(row);
      const unresolved = row.dataset.unresolved === "true";
      row.hidden = !matches || (view === "review" && !unresolved);
      if (matches && unresolved) reviewMatches += 1;
      if (matches) peopleMatches += 1;
    }

    chartView.hidden = view !== "chart";
    reviewView.hidden = view === "chart";
    reviewView.scrollTop = 0;
    expandButton.hidden = view !== "chart";
    groupToolbar.hidden = view !== "chart";
    canvasControls.hidden = view !== "chart";
    const visibleCount = view === "chart" ? matchingNodes.size : view === "review" ? reviewMatches : peopleMatches;
    emptyMessage.hidden = visibleCount > 0;
    emptyMessage.textContent = view === "chart" && reviewMatches > 0
      ? `${reviewMatches} matching ${reviewMatches === 1 ? "person has" : "people have"} an unresolved manager. Open Needs review to see them.`
      : "No people match these filters. Try another department or search.";

    if (!visibleCount) {
      chartView.hidden = true;
      reviewView.hidden = true;
      canvasControls.hidden = true;
    }

    if (view === "review") {
      resultCount.textContent = `${reviewMatches} ${reviewMatches === 1 ? "person needs" : "people need"} review`;
    } else if (view === "people") {
      resultCount.textContent = `${peopleMatches} ${peopleMatches === 1 ? "person" : "people"} · accepted managers and unresolved decisions`;
    } else if (filtered) {
      resultCount.textContent = `${visibleCount} matching ${visibleCount === 1 ? "person" : "people"} · real ancestors kept for context`;
    } else if (groupFilter.value) {
      const lines = [...matchingNodes].filter((node) => node.dataset.manager).length;
      resultCount.textContent = `${visibleCount} people · ${lines} inferred reporting lines in this group`;
    } else {
      resultCount.textContent = originalCount;
    }
    updateExpandButton();
    requestLayout(center);
  }

  for (const button of viewButtons) {
    button.addEventListener("click", () => {
      view = button.dataset.view;
      for (const other of viewButtons) other.setAttribute("aria-pressed", String(other === button));
      explanation.textContent = view === "review"
        ? "Only people without an accepted reporting line appear here. The candidate shown is unconfirmed. Open a person to see why no line was added."
        : view === "people" ? "Everyone in this company is listed here. Accepted managers are named; unconfirmed candidates stay separate from reporting lines."
        : "Follow the lines from each manager to their direct reports. Select a person for details, or open the report count to see their team.";
      updatePeople();
    });
  }

  function searchPeople() {
    if (department.value || peopleSearch.value.trim()) groupFilter.value = "";
    updatePeople();
  }
  peopleSearch.addEventListener("input", searchPeople);
  department.addEventListener("change", searchPeople);
  groupFilter.addEventListener("change", () => updatePeople());
  expandButton.addEventListener("click", () => {
    const visibleBranches = branches.filter((branch) => !branch.closest(".reporting-group").hidden
      && !branch.closest(".tree-node").hidden);
    const open = !visibleBranches.every((branch) => branch.open);
    for (const branch of visibleBranches) branch.open = open;
    updateExpandButton();
    requestLayout(true);
  });
  for (const branch of branches) branch.addEventListener("toggle", updateExpandButton);

  zoomOut.addEventListener("click", () => setZoom(zoom - 0.1));
  zoomIn.addEventListener("click", () => setZoom(zoom + 0.1));
  document.querySelector("#zoom-fit").addEventListener("click", fitChart);
  document.querySelector("#zoom-reset").addEventListener("click", () => {
    setZoom(1, false);
    requestLayout(true);
  });

  let drag = null;
  chartView.addEventListener("pointerdown", (event) => {
    if (event.pointerType !== "mouse" || event.button !== 0
      || event.target.closest("button, a, input, select, summary")) return;
    drag = { x: event.clientX, y: event.clientY, left: chartView.scrollLeft, top: chartView.scrollTop };
    chartView.setPointerCapture(event.pointerId);
    chartView.classList.add("is-panning");
  });
  chartView.addEventListener("pointermove", (event) => {
    if (!drag) return;
    chartView.scrollLeft = drag.left - (event.clientX - drag.x);
    chartView.scrollTop = drag.top - (event.clientY - drag.y);
  });
  function stopPanning() {
    drag = null;
    chartView.classList.remove("is-panning");
  }
  chartView.addEventListener("pointerup", stopPanning);
  chartView.addEventListener("pointercancel", stopPanning);
  chartView.addEventListener("keydown", (event) => {
    if (event.target !== chartView) return;
    const moves = { ArrowLeft: [-90, 0], ArrowRight: [90, 0], ArrowUp: [0, -90], ArrowDown: [0, 90] };
    const move = moves[event.key];
    if (!move) return;
    event.preventDefault();
    chartView.scrollBy(move[0], move[1]);
  });

  document.querySelector("#show-truth").addEventListener("change", (event) => {
    for (const status of document.querySelectorAll("[data-confidence]")) {
      const correct = status.dataset.correct === "true";
      const normalText = status.classList.contains("card-status")
        ? `${status.dataset.confidence} confidence` : status.dataset.confidence;
      status.textContent = event.target.checked
        ? `${status.dataset.confidence} · ${correct ? "correct" : "incorrect"}` : normalText;
      status.classList.toggle("wrong", event.target.checked && !correct);
    }
  });

  new ResizeObserver(() => requestLayout()).observe(canvas);
  window.addEventListener("resize", () => requestLayout());
  updatePeople();
  requestAnimationFrame(() => {
    // Start at a readable size. Fit can show a wider team in one view when needed.
    setZoom(1, false);
    requestLayout(true);
  });
}

const records = document.querySelector("#company-records");
const dialog = document.querySelector("#person-dialog");

if (records && dialog) {
  const people = new Map(JSON.parse(records.textContent).map((person) => [person.id, person]));
  const managerButton = document.querySelector("#dialog-manager");
  const reasons = document.querySelector("#dialog-reasons");
  const percentFormatter = new Intl.NumberFormat("en-US", {
    style: "percent", minimumFractionDigits: 1, maximumFractionDigits: 1,
  });
  const formatPercent = (value) => percentFormatter.format(value);
  const formatPoints = (value) => formatPercent(value).replace("%", "");

  function setText(id, value) {
    document.getElementById(id).textContent = value;
  }

  function showPerson(personId) {
    const person = people.get(personId);
    if (!person) return;

    const manager = people.get(person.predictedManagerId);
    const candidate = people.get(person.bestCandidateId);
    const truth = people.get(person.groundTruthManagerId);
    const isRoot = person.inferredLevel === "CEO";
    const nameParts = person.name.split(/\s+/);

    setText("dialog-avatar", `${nameParts[0][0]}${nameParts.at(-1)[0]}`);
    setText("dialog-name", person.name);
    setText("dialog-title", person.title || "Title missing");
    setText("dialog-department", person.inferredDepartment);
    setText("dialog-level", person.inferredLevel);
    setText("dialog-team", person.team);
    setText("dialog-location", person.location);

    managerButton.hidden = !manager;
    if (manager) {
      managerButton.dataset.person = manager.id;
      setText("dialog-manager-name", manager.name);
      setText("dialog-decision-title", "Inferred manager");
      setText("dialog-decision-description", manager.title || "Title missing");
    } else {
      delete managerButton.dataset.person;
      setText("dialog-manager-name", "");
      setText("dialog-decision-title", isRoot ? "Company root" : "Manager unresolved");
      setText("dialog-decision-description", isRoot
        ? "The title identifies this person as the CEO. No manager is expected."
        : candidate
          ? `${candidate.name} is the leading candidate, but the match did not clear both acceptance checks. No reporting line was added.`
          : "No suitable manager candidate was found in this company.");
    }

    document.querySelector("#dialog-decision-numbers").hidden = isRoot;
    document.querySelector("#dialog-confidence-note").hidden = isRoot;
    setText("dialog-confidence", formatPercent(person.confidence));
    setText("dialog-margin", formatPoints(person.margin));

    reasons.replaceChildren();
    for (const reason of person.reasons) {
      const item = document.createElement("li");
      const check = document.createElement("span");
      check.setAttribute("aria-hidden", "true");
      check.textContent = "✓";
      item.append(check, document.createTextNode(reason));
      reasons.append(item);
    }
    document.querySelector("#dialog-signals").hidden = person.reasons.length === 0;

    setText("dialog-truth-manager", truth
      ? `Generated direct manager: ${truth.name} · ${truth.title || "Title missing"}.`
      : "This person is the generated company root.");
    setText("dialog-truth-result", manager
      ? `The inferred reporting line is ${person.isCorrect ? "correct" : "incorrect"}.`
      : isRoot ? "" : "The model left this manager unresolved.");
    setText("dialog-original-title", person.title || "Missing");
    setText("dialog-original-department", person.rawDepartment);
    setText("dialog-record-id", person.id);
    setText("dialog-noise", person.noiseProfile.join(", ").replaceAll("_", " "));

    document.querySelector("#dialog-truth-disclosure").open = false;
    document.querySelector("#dialog-record-disclosure").open = false;
    dialog.scrollTop = 0;

    if (dialog.open) {
      // Manager navigation stays in the same dialog and keeps keyboard focus inside it.
      document.querySelector("#dialog-name").focus({ preventScroll: true });
    } else {
      dialog.showModal();
    }
  }

  document.addEventListener("click", (event) => {
    const personButton = event.target.closest("[data-person]");
    if (!personButton) return;

    // A person button inside a branch summary should not fold the team.
    event.preventDefault();
    showPerson(personButton.dataset.person);
  });

  dialog.addEventListener("click", (event) => {
    if (event.target !== dialog) return;
    const bounds = dialog.getBoundingClientRect();
    if (event.clientX < bounds.left || event.clientX > bounds.right
      || event.clientY < bounds.top || event.clientY > bounds.bottom) {
      dialog.close();
    }
  });
}
