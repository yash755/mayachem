document.addEventListener("DOMContentLoaded", function() {
  const tbody = document.querySelector("#locations-table tbody");
  const addForm = document.getElementById("add-location-form");
  const nameInput = document.getElementById("loc-name");

  function fetchLocations() {
    fetch("/api/locations").then(r => r.json()).then(data => {
      tbody.innerHTML = "";
      data.forEach(loc => {
        const tr = document.createElement("tr");

        const tdName = document.createElement("td");
        tdName.textContent = loc.name;
        tdName.dataset.id = loc.id;
        tdName.style.cursor = "pointer";

        // clicking name -> edit inline
        tdName.addEventListener("click", () => {
          startEdit(loc.id, loc.name, tdName);
        });

        const tdActions = document.createElement("td");
        tdActions.className = "text-end";

        const del = document.createElement("button");
        del.className = "btn btn-sm btn-outline-danger me-2";
        del.textContent = "Delete";
        del.addEventListener("click", () => {
          if (!confirm("Delete this location? This will also remove its leads.")) return;
          fetch(`/api/locations/${loc.id}`, { method: "DELETE" }).then(_ => {
            fetchLocations();
            // also attempt to notify leads page selectors by dispatching an event
            window.dispatchEvent(new Event("locations:changed"));
          }).catch(err => alert("Error: " + err));
        });

        tdActions.appendChild(del);
        tr.appendChild(tdName);
        tr.appendChild(tdActions);
        tbody.appendChild(tr);
      });
    });
  }

  function startEdit(id, currentName, td) {
    const input = document.createElement("input");
    input.type = "text";
    input.value = currentName;
    input.className = "form-control form-control-sm";
    td.innerHTML = "";
    td.appendChild(input);
    input.focus();

    function finish(save) {
      const newName = input.value.trim();
      if (save && newName && newName !== currentName) {
        fetch(`/api/locations/${id}`, {
          method: "PUT",
          headers: {"Content-Type": "application/json"},
          body: JSON.stringify({ name: newName }),
        }).then(r => {
          if (!r.ok) return r.json().then(j => Promise.reject(j));
          return r.json();
        }).then(_ => {
          fetchLocations();
          window.dispatchEvent(new Event("locations:changed"));
        }).catch(err => alert(err?.error || "Error updating"));
      } else {
        // cancel or no-change
        fetchLocations();
      }
    }

    input.addEventListener("blur", () => finish(true));
    input.addEventListener("keydown", (e) => {
      if (e.key === "Enter") {
        e.preventDefault();
        finish(true);
      } else if (e.key === "Escape") {
        finish(false);
      }
    });
  }

  addForm.addEventListener("submit", (ev) => {
    ev.preventDefault();
    const name = nameInput.value.trim();
    if (!name) return alert("Name required");
    fetch("/api/locations", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({ name })
    }).then(r => {
      if (!r.ok) return r.json().then(j => Promise.reject(j));
      return r.json();
    }).then(_ => {
      nameInput.value = "";
      fetchLocations();
      window.dispatchEvent(new Event("locations:changed"));
    }).catch(err => alert(err?.error || "Error adding location"));
  });

  // initial
  fetchLocations();
});
