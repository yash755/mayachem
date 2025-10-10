// static/js/leads.js
document.addEventListener("DOMContentLoaded", function() {
  // DOM refs
  const leadLocationSelect = document.getElementById("lead-location");
  const filterSelect = document.getElementById("filter-location");
  const dealFilterSelect = document.getElementById("filter-deal-status");
  const clearFiltersBtn = document.getElementById("clear-filters");
  const leadsTableBody = document.querySelector("#leads-table tbody");
  const addLeadForm = document.getElementById("add-lead-form");
  const currentLocationName = document.getElementById("current-location-name");

  // --- Helpers ---
  function escapeHtml(s) {
    if (s === null || s === undefined) return "";
    return String(s)
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;");
  }
  function escapeAttr(s) {
    if (s === null || s === undefined) return "";
    return String(s)
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#39;");
  }

  function getCurrentDealSelections() {
    if (!dealFilterSelect) return null;
    const sel = Array.from(dealFilterSelect.selectedOptions).map(o => o.value).filter(Boolean);
    return sel.length ? sel : null;
  }

  // --- Populate deal status filter from DEAL_CHOICES ---
  function populateDealFilter() {
    if (!dealFilterSelect) return;
    dealFilterSelect.innerHTML = "";
    if (Array.isArray(DEAL_CHOICES)) {
      DEAL_CHOICES.forEach(s => {
        const opt = document.createElement("option");
        opt.value = s;
        opt.textContent = s;
        dealFilterSelect.appendChild(opt);
      });
    }
  }

  // --- Fetch / populate locations into selects ---
  function fetchLocations() {
    if (!leadLocationSelect || !filterSelect) return Promise.resolve([]);

    leadLocationSelect.innerHTML = '<option value="">Select location</option>';
    filterSelect.innerHTML = '<option value="">All locations</option>';

    return fetch("/api/locations", { credentials: 'same-origin' })
      .then(r => {
        if (!r.ok) return r.text().then(t => { throw { status: r.status, body: t }; });
        return r.json();
      })
      .then(data => {
        data.forEach(loc => {
          const opt = document.createElement("option");
          opt.value = loc.id;
          opt.textContent = loc.name;
          leadLocationSelect.appendChild(opt);

          const opt2 = opt.cloneNode(true);
          filterSelect.appendChild(opt2);
        });
        return data;
      })
      .catch(err => {
        console.error("fetchLocations error:", err);
        return [];
      });
  }

  // --- Load leads and render rows ---
  // accepts optional location_id, location_name, and dealStatuses (array)
  function loadLeads(location_id = null, location_name = null, dealStatuses = null) {
    const params = new URLSearchParams();
    if (location_id) params.append("location_id", location_id);
    if (dealStatuses && Array.isArray(dealStatuses) && dealStatuses.length) {
      params.append("deal_status", dealStatuses.join(","));
    }
    let url = "/api/leads";
    const qs = params.toString();
    if (qs) url += `?${qs}`;

    // show loading row
    leadsTableBody.innerHTML = `<tr><td colspan="7">Loading...</td></tr>`;

    fetch(url, { credentials: 'same-origin' })
      .then(r => {
        if (!r.ok) return r.text().then(t => { throw { status: r.status, body: t }; });
        return r.json();
      })
      .then(data => {
        renderLeadsRows(data);
        currentLocationName.textContent = location_name ? `(${location_name})` : "(All)";
      })
      .catch(err => {
        console.error("loadLeads error:", err);
        leadsTableBody.innerHTML = `<tr><td colspan="7" class="text-danger">Error loading leads</td></tr>`;
      });
  }

  // --- Render rows with Edit + Delete actions ---
// --- Render rows with Edit + Delete actions (and mobile cards) ---
function renderLeadsRows(leads) {
  // Table body (desktop)
  leadsTableBody.innerHTML = "";
  // Cards container (mobile)
  const cardsContainer = document.getElementById("leads-cards");
  if (cardsContainer) cardsContainer.innerHTML = "";

  if (!Array.isArray(leads) || leads.length === 0) {
    // Table fallback
    leadsTableBody.innerHTML = `<tr><td colspan="7" class="text-muted">No leads found</td></tr>`;
    // Cards fallback
    if (cardsContainer) {
      const empty = document.createElement("div");
      empty.className = "text-muted";
      empty.textContent = "No leads found";
      cardsContainer.appendChild(empty);
    }
    return;
  }

  // Helper to build card DOM for mobile
  function buildCard(lead) {
    const card = document.createElement("div");
    card.className = "lead-card";

    // top row: Name + Deal status
    const top = document.createElement("div");
    top.className = "lead-row";
    const nameDiv = document.createElement("div");
    nameDiv.innerHTML = `<strong>${escapeHtml(lead.name || "")}</strong>`;
    const statusDiv = document.createElement("div");
    statusDiv.innerHTML = `<small>${escapeHtml(lead.deal_status || "")}</small>`;
    top.appendChild(nameDiv);
    top.appendChild(statusDiv);

    // middle: location, indiamart link, address
    const meta = document.createElement("div");
    meta.className = "lead-meta";
    const locationText = lead.location_name ? `<div><strong>Location:</strong> ${escapeHtml(lead.location_name)}</div>` : "";
    const linkText = lead.indiamart_link ? `<div><strong>IndiaMART:</strong> <a href="${escapeAttr(lead.indiamart_link)}" target="_blank" rel="noopener noreferrer">Link</a></div>` : "";
    const addressText = lead.address ? `<div><strong>Address:</strong> ${escapeHtml(lead.address)}</div>` : "";
    const commentsText = lead.comments ? `<div><strong>Comments:</strong> ${escapeHtml(lead.comments)}</div>` : "";
    meta.innerHTML = locationText + linkText + addressText + commentsText;

    // actions row: Edit + Delete (reuse existing handlers by creating buttons)
    const actions = document.createElement("div");
    actions.className = "lead-actions";

    const editBtn = document.createElement("button");
    editBtn.className = "btn btn-sm btn-outline-primary";
    editBtn.textContent = "Edit";
    editBtn.addEventListener("click", () => {
      // create a temporary table row and invoke startInlineEdit to reuse logic:
      // create a fake <tr> and call startInlineEdit — then swap the cards after save by reload
      // Simpler: call startInlineEdit by finding the corresponding existing table row if present
        if (window.innerWidth < 768) {
          openEditModal(lead);
        } else {
      // Desktop → inline edit
        const tableRow = leadsTableBody.querySelector(`tr[data-lead-id="${lead.id}"]`);
        if (tableRow) startInlineEdit(tableRow, lead);
        }
      });

    const delBtn = document.createElement("button");
    delBtn.className = "btn btn-sm btn-outline-danger";
    delBtn.textContent = "Delete";
    delBtn.addEventListener("click", () => handleDeleteLead(lead.id));

    actions.appendChild(editBtn);
    actions.appendChild(delBtn);

    card.appendChild(top);
    card.appendChild(meta);
    card.appendChild(actions);
    return card;
  }

  // Build table rows and cards
  leads.forEach(lead => {
    // --- Table row (desktop)
    const tr = document.createElement("tr");
    tr.dataset.leadId = lead.id;

    tr.innerHTML = `
      <td class="cell-name">${escapeHtml(lead.name)}</td>
      <td class="cell-location">${escapeHtml(lead.location_name || "")}</td>
      <td class="cell-link">${lead.indiamart_link ? `<a href="${escapeAttr(lead.indiamart_link)}" target="_blank" rel="noopener noreferrer">Link</a>` : ""}</td>
      <td class="cell-status">${escapeHtml(lead.deal_status || "")}</td>
      <td class="cell-address">${escapeHtml(lead.address || "")}</td>
      <td class="cell-comments">${escapeHtml(lead.comments || "")}</td>
      <td class="cell-actions">
        <button class="btn btn-sm btn-outline-primary btn-edit me-1">Edit</button>
        <button class="btn btn-sm btn-outline-danger btn-delete">Delete</button>
      </td>
    `;

    // attach handlers for table buttons
    const delBtn = tr.querySelector(".btn-delete");
    const editBtn = tr.querySelector(".btn-edit");
    delBtn.addEventListener("click", () => handleDeleteLead(lead.id));
    editBtn.addEventListener("click", () => startInlineEdit(tr, lead));
    leadsTableBody.appendChild(tr);

    // --- Mobile card
    if (cardsContainer) {
      const card = buildCard(lead);
      // attach a data attribute so devtools can inspect mapping
      card.dataset.leadId = lead.id;
      cardsContainer.appendChild(card);
    }
  });
}

// --- Mobile Edit Modal ---
function openEditModal(lead) {
  const modal = new bootstrap.Modal(document.getElementById("editLeadModal"));
  
  // populate form
  document.getElementById("edit-lead-id").value = lead.id;
  document.getElementById("edit-lead-name").value = lead.name || "";
  document.getElementById("edit-lead-indiamart").value = lead.indiamart_link || "";
  document.getElementById("edit-lead-address").value = lead.address || "";
  document.getElementById("edit-lead-comments").value = lead.comments || "";

  // populate deal status dropdown
  const statusSel = document.getElementById("edit-lead-status");
  statusSel.innerHTML = "";
  DEAL_CHOICES.forEach(s => {
    const opt = document.createElement("option");
    opt.value = s;
    opt.textContent = s;
    if ((lead.deal_status || "") === s) opt.selected = true;
    statusSel.appendChild(opt);
  });

  // populate locations dropdown (reuse fetched list)
  const locSel = document.getElementById("edit-lead-location");
  locSel.innerHTML = '<option value="">Select location</option>';
  fetch("/api/locations", { credentials: 'same-origin' })
    .then(r => r.json())
    .then(data => {
      data.forEach(l => {
        const opt = document.createElement("option");
        opt.value = l.id;
        opt.textContent = l.name;
        if (String(l.id) === String(lead.location_id)) opt.selected = true;
        locSel.appendChild(opt);
      });
    });

  modal.show();
}

// handle modal form save
document.getElementById("edit-lead-form").addEventListener("submit", function(ev) {
  ev.preventDefault();

  const id = document.getElementById("edit-lead-id").value;
  const payload = {
    name: document.getElementById("edit-lead-name").value.trim(),
    location_id: document.getElementById("edit-lead-location").value || null,
    indiamart_link: document.getElementById("edit-lead-indiamart").value.trim() || null,
    deal_status: document.getElementById("edit-lead-status").value || null,
    address: document.getElementById("edit-lead-address").value.trim() || null,
    comments: document.getElementById("edit-lead-comments").value.trim() || null
  };

  fetch(`/api/leads/${id}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    credentials: 'same-origin',
    body: JSON.stringify(payload)
  })
    .then(r => {
      if (!r.ok) return r.json().then(j => Promise.reject(j));
      return r.json();
    })
    .then(() => {
      bootstrap.Modal.getInstance(document.getElementById("editLeadModal")).hide();
      const locVal = filterSelect ? filterSelect.value || null : null;
      const locText = (filterSelect && filterSelect.selectedIndex >= 0) ? filterSelect.options[filterSelect.selectedIndex].text : null;
      loadLeads(locVal, locText, getCurrentDealSelections());
    })
    .catch(err => {
      console.error("update error:", err);
      alert(err?.error || "Error updating lead");
    });
});


  // --- Delete lead ---
  function handleDeleteLead(id) {
    if (!confirm("Delete lead?")) return;
    fetch(`/api/leads/${id}`, { method: "DELETE", credentials: 'same-origin' })
      .then(r => {
        if (!r.ok) return r.text().then(t => Promise.reject(t));
        // reload with current filters
        const locVal = filterSelect ? filterSelect.value || null : null;
        const locText = (filterSelect && filterSelect.selectedIndex >= 0) ? filterSelect.options[filterSelect.selectedIndex].text : null;
        loadLeads(locVal, locText, getCurrentDealSelections());
      })
      .catch(err => {
        console.error("delete error:", err);
        alert("Error deleting lead");
      });
  }

  // --- Inline edit: transform row into inputs ---
 // --- Inline edit: transform row into inputs (robust version) ---
async function startInlineEdit(tr, lead) {
  try {
    // ensure latest locations are available
    const locations = await fetchLocations();

    // helper to safe-query cell and throw informative error if missing
    function cellOrThrow(selector) {
      const node = tr.querySelector(selector);
      if (!node) {
        console.error(`Expected cell "${selector}" not found in row. Row HTML:`, tr.innerHTML);
      }
      return node;
    }

    // Build inputs
    const nameInput = document.createElement("input");
    nameInput.type = "text";
    nameInput.value = lead.name || "";
    nameInput.className = "form-control form-control-sm";

    const locSelect = document.createElement("select");
    locSelect.className = "form-select form-select-sm";
    const emptyOpt = document.createElement("option");
    emptyOpt.value = "";
    emptyOpt.textContent = "Select location";
    locSelect.appendChild(emptyOpt);
    locations.forEach(l => {
      const o = document.createElement("option");
      o.value = l.id;
      o.text = l.name;
      if (lead.location_id === l.id || String(lead.location_id) === String(l.id)) o.selected = true;
      locSelect.appendChild(o);
    });

    const linkInput = document.createElement("input");
    linkInput.type = "url";
    linkInput.value = lead.indiamart_link || "";
    linkInput.className = "form-control form-control-sm";

    // Deal status dropdown (populated from DEAL_CHOICES)
    let statusSelect = null;
    let statusFallback = null;
    if (typeof DEAL_CHOICES !== "undefined" && Array.isArray(DEAL_CHOICES)) {
      statusSelect = document.createElement("select");
      statusSelect.className = "form-select form-select-sm";
      DEAL_CHOICES.forEach(s => {
        const so = document.createElement("option");
        so.value = s;
        so.textContent = s;
        if ((lead.deal_status || "") === s) so.selected = true;
        statusSelect.appendChild(so);
      });
    } else {
      statusFallback = document.createElement("input");
      statusFallback.type = "text";
      statusFallback.value = lead.deal_status || "";
      statusFallback.className = "form-control form-control-sm";
    }

    const addressInput = document.createElement("input");
    addressInput.type = "text";
    addressInput.value = lead.address || "";
    addressInput.className = "form-control form-control-sm";

    const commentsInput = document.createElement("input");
    commentsInput.type = "text";
    commentsInput.value = lead.comments || "";
    commentsInput.className = "form-control form-control-sm";

    // actions: Save + Cancel
    const saveBtn = document.createElement("button");
    saveBtn.className = "btn btn-sm btn-primary me-1";
    saveBtn.textContent = "Save";

    const cancelBtn = document.createElement("button");
    cancelBtn.className = "btn btn-sm btn-secondary";
    cancelBtn.textContent = "Cancel";

    // Replace each cell safely (log if a cell wasn't found)
    const nameCell = cellOrThrow(".cell-name");
    const locCell = cellOrThrow(".cell-location");
    const linkCell = cellOrThrow(".cell-link");
    const statusCell = cellOrThrow(".cell-status");
    const addressCell = cellOrThrow(".cell-address");
    const commentsCell = cellOrThrow(".cell-comments");
    const actionsCell = cellOrThrow(".cell-actions");

    if (nameCell) { nameCell.innerHTML = ""; nameCell.appendChild(nameInput); }
    if (locCell) { locCell.innerHTML = ""; locCell.appendChild(locSelect); }
    if (linkCell) { linkCell.innerHTML = ""; linkCell.appendChild(linkInput); }
    if (statusCell) {
      statusCell.innerHTML = "";
      if (statusSelect) statusCell.appendChild(statusSelect);
      else statusCell.appendChild(statusFallback);
    }
    if (addressCell) { addressCell.innerHTML = ""; addressCell.appendChild(addressInput); }
    if (commentsCell) { commentsCell.innerHTML = ""; commentsCell.appendChild(commentsInput); }

    // Put buttons into actions cell
    if (actionsCell) {
      actionsCell.innerHTML = "";
      actionsCell.appendChild(saveBtn);
      actionsCell.appendChild(cancelBtn);
    }

    // focus first input
    nameInput.focus();

    // cancel handler: reload leads to restore original
    cancelBtn.addEventListener("click", (ev) => {
      ev.preventDefault();
      const locVal = filterSelect ? filterSelect.value || null : null;
      const locText = (filterSelect && filterSelect.selectedIndex >= 0) ? filterSelect.options[filterSelect.selectedIndex].text : null;
      loadLeads(locVal, locText, getCurrentDealSelections());
    });

    // save handler: send PUT
    saveBtn.addEventListener("click", (ev) => {
      ev.preventDefault();
      let chosenStatus = null;
      if (statusSelect) chosenStatus = (statusSelect.value || "").trim() || null;
      else chosenStatus = (statusFallback.value || "").trim() || null;

      const payload = {
        name: nameInput.value.trim(),
        location_id: locSelect.value || null,
        indiamart_link: linkInput.value.trim() || null,
        deal_status: chosenStatus,
        address: addressInput.value.trim() || null,
        comments: commentsInput.value.trim() || null
      };
      if (!payload.name) {
        alert("Name is required");
        nameInput.focus();
        return;
      }

      fetch(`/api/leads/${lead.id}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        credentials: 'same-origin',
        body: JSON.stringify(payload)
      })
        .then(r => {
          if (!r.ok) return r.json().then(j => Promise.reject(j));
          return r.json();
        })
        .then(updated => {
          const locVal = filterSelect ? filterSelect.value || null : null;
          const locText = (filterSelect && filterSelect.selectedIndex >= 0) ? filterSelect.options[filterSelect.selectedIndex].text : null;
          loadLeads(locVal, locText, getCurrentDealSelections());
        })
        .catch(err => {
          console.error("update error:", err);
          alert(err?.error || "Error updating lead");
        });
    });

  } catch (err) {
    console.error("startInlineEdit error:", err);
    alert("Unable to start edit. See console for details.");
  }
}


  // --- Add lead form handler ---
  if (addLeadForm) {
    addLeadForm.addEventListener("submit", function(ev) {
      ev.preventDefault();
      const payload = {
        name: document.getElementById("lead-name").value.trim(),
        location_id: document.getElementById("lead-location").value || null,
        indiamart_link: document.getElementById("lead-indiamart").value.trim() || null,
        deal_status: document.getElementById("lead-deal-status").value || null,
        address: document.getElementById("lead-address") ? document.getElementById("lead-address").value.trim() || null : null,
        comments: document.getElementById("lead-comments").value.trim() || null
      };
      if (!payload.name) {
        alert("Lead name required");
        return;
      }
      fetch("/api/leads", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: 'same-origin',
        body: JSON.stringify(payload)
      }).then(r => {
        if (!r.ok) return r.json().then(j => Promise.reject(j));
        return r.json();
      }).then(_ => {
        addLeadForm.reset();
        const locVal = filterSelect ? filterSelect.value || null : null;
        const locText = (filterSelect && filterSelect.selectedIndex >= 0) ? filterSelect.options[filterSelect.selectedIndex].text : null;
        loadLeads(locVal, locText, getCurrentDealSelections());
      }).catch(err => {
        console.error("add lead error:", err);
        alert(err?.error || "Error adding lead");
      });
    });
  }

  // --- filter change for location ---
  if (filterSelect) {
    filterSelect.addEventListener("change", function() {
      const val = this.value || null;
      const text = this.options[this.selectedIndex] ? this.options[this.selectedIndex].text : null;
      loadLeads(val, text, getCurrentDealSelections());
    });
  }

  // --- filter change for deal status multi-select ---
  if (dealFilterSelect) {
    dealFilterSelect.addEventListener("change", function() {
      const selected = getCurrentDealSelections();
      const locVal = filterSelect ? filterSelect.value || null : null;
      const locText = (filterSelect && filterSelect.selectedIndex >= 0) ? filterSelect.options[filterSelect.selectedIndex].text : null;
      loadLeads(locVal, locText, selected);
    });
  }

  // Clear filters button
  if (clearFiltersBtn) {
    clearFiltersBtn.addEventListener("click", function() {
      if (filterSelect) filterSelect.value = "";
      if (dealFilterSelect) {
        Array.from(dealFilterSelect.options).forEach(o => o.selected = false);
      }
      loadLeads(null, null, null);
    });
  }

  // update locations if changed elsewhere
  window.addEventListener("locations:changed", function() {
    fetchLocations().then(() => {
      const locVal = filterSelect ? filterSelect.value || null : null;
      const locText = (filterSelect && filterSelect.selectedIndex >= 0) ? filterSelect.options[filterSelect.selectedIndex].text : null;
      loadLeads(locVal, locText, getCurrentDealSelections());
    });
  });

  // initial setup
  populateDealFilter();
  fetchLocations().then(() => {
    const initialDealSelections = getCurrentDealSelections();
    loadLeads(null, null, initialDealSelections);
  });
});
