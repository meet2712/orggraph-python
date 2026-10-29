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
  const nodes = [...chartView.querySelectorAll(".tree-node")];
  const reviewRows = [...reviewView.querySelectorAll("[data-review-person]")];
  const branches = [...chartView.querySelectorAll("details.branch")];
  const expandButton = document.querySelector("#expand-teams");
  const emptyMessage = document.querySelector("#no-people");
  const resultCount = document.querySelector("#people-result-count");
  const explanation = document.querySelector("#chart-explanation");
  const originalCount = resultCount.textContent;
  let view = "chart";

  function matchesFilters(row) {
    const query = peopleSearch.value.trim().toLowerCase();
    return (!department.value || row.dataset.department === department.value)
      && row.dataset.search.includes(query);
  }

  function updateExpandButton() {
    const allOpen = branches.length > 0 && branches.every((branch) => branch.open);
    expandButton.textContent = allOpen ? "Collapse all" : "Expand all";
    expandButton.disabled = branches.length === 0;
  }

  function updatePeople() {
    const matchingNodes = new Set(nodes.filter(matchesFilters));
    const filtered = Boolean(department.value || peopleSearch.value.trim());

    // Keep the ancestors of a match, so filtering never invents a reporting line.
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

    let reviewMatches = 0;
    for (const row of reviewRows) {
      row.hidden = !matchesFilters(row);
      if (!row.hidden) reviewMatches += 1;
    }

    chartView.hidden = view !== "chart";
    reviewView.hidden = view !== "review";
    expandButton.hidden = view !== "chart";
    const visibleCount = view === "chart" ? matchingNodes.size : reviewMatches;
    emptyMessage.hidden = visibleCount > 0;

    if (!visibleCount) {
      chartView.hidden = true;
      reviewView.hidden = true;
    }

    resultCount.textContent = view === "review"
      ? `${reviewMatches} ${reviewMatches === 1 ? "person needs" : "people need"} review`
      : filtered ? `${visibleCount} matching ${visibleCount === 1 ? "person" : "people"} · ancestors kept for context` : originalCount;
    updateExpandButton();
  }

  for (const button of viewButtons) {
    button.addEventListener("click", () => {
      view = button.dataset.view;
      for (const other of viewButtons) {
        other.setAttribute("aria-pressed", String(other === button));
      }
      explanation.textContent = view === "review"
        ? "These people have no accepted manager match. Select a person to see the leading candidate and why the model left it unresolved."
        : "Each line is an accepted manager match. Select a person to see the evidence. Separate groups stay disconnected when a manager is unknown.";
      updatePeople();
    });
  }

  peopleSearch.addEventListener("input", updatePeople);
  department.addEventListener("change", updatePeople);
  expandButton.addEventListener("click", () => {
    const open = !branches.every((branch) => branch.open);
    for (const branch of branches) branch.open = open;
    updateExpandButton();
  });
  for (const branch of branches) branch.addEventListener("toggle", updateExpandButton);

  document.querySelector("#show-truth").addEventListener("change", (event) => {
    for (const status of document.querySelectorAll("[data-confidence]")) {
      const correct = status.dataset.correct === "true";
      status.textContent = event.target.checked
        ? `${status.dataset.confidence} · ${correct ? "correct" : "incorrect"}`
        : status.dataset.confidence;
      status.classList.toggle("wrong", event.target.checked && !correct);
    }
  });

  updatePeople();
}

const records = document.querySelector("#company-records");
const dialog = document.querySelector("#person-dialog");

if (records && dialog) {
  const people = new Map(JSON.parse(records.textContent).map((person) => [person.id, person]));
  const managerButton = document.querySelector("#dialog-manager");
  const reasons = document.querySelector("#dialog-reasons");
  const formatPercent = (value) => `${(value * 100).toFixed(1)}%`;
  const formatPoints = (value) => (value * 100).toFixed(1);

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
