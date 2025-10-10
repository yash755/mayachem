// static/sales.js (defensive drop-in)
(function () {
  "use strict";

  function logError(err) {
    try {
      console.error("sales.js error:", err);
      // show small banner on page so it's obvious
      var bannerId = "sales-js-error-banner";
      var existing = document.getElementById(bannerId);
      if (!existing && document.body) {
        var b = document.createElement("div");
        b.id = bannerId;
        b.style.background = "#f8d7da";
        b.style.color = "#842029";
        b.style.padding = "8px 12px";
        b.style.fontFamily = "system-ui, sans-serif";
        b.style.fontSize = "13px";
        b.style.position = "fixed";
        b.style.right = "12px";
        b.style.top = "12px";
        b.style.zIndex = 9999;
        b.style.border = "1px solid #f5c2c7";
        b.textContent = "sales.js error — check console for details";
        document.body.appendChild(b);
      }
    } catch (e) {
      // swallow
    }
  }

  // safe helpers
  function qs(sel, root) {
    root = root || document;
    try { return root.querySelector(sel); } catch (e) { return null; }
  }
  function qsa(sel, root) {
    root = root || document;
    try { return Array.from(root.querySelectorAll(sel)); } catch (e) { return []; }
  }
  function safeParseFloat(v) {
    var n = parseFloat(String(v || "").replace(/,/g, ""));
    return Number.isFinite(n) ? n : 0;
  }

  try {
    document.addEventListener("DOMContentLoaded", function () {
      try {
        // Elements (guarded)
        var saleTypeEl = qs("#sale_type");
        var billModeEl = qs("#bill-mode");
        var cashModeEl = qs("#cash-mode");

        var addRowBillBtn = qs("#add-row-bill");
        var itemsBodyBill = qs("#items-body-bill");

        var addRowCashBtn = qs("#add-row-cash");
        var itemsBodyCash = qs("#items-body-cash");

        var freightEl = qs("#freight");
        var totalCpEl = qs("#total_cp");
        var totalSpEl = qs("#total_sp");
        var plEl = qs("#pl");

        if (!itemsBodyBill || !itemsBodyCash || !saleTypeEl) {
          // Not the page we expect — bail quietly
          return;
        }

        // helpers
        function qtyToKg(qty, unit) {
          var q = safeParseFloat(qty);
          if (unit === "ton") return q * 1000;
          return q;
        }

        // Bill totals
        function computeBillTotals() {
          try {
            var rows = qsa(".item-row", itemsBodyBill);
            var totalCp = 0, totalSp = 0;
            rows.forEach(function (r) {
              var qty = qs('input[name="quantity[]"]', r);
              var unit = qs('select[name="unit[]"]', r);
              var cost = qs('input[name="cost_rate[]"]', r);
              var sell = qs('input[name="sell_rate[]"]', r);
              var qtyKg = qtyToKg(qty ? qty.value : 0, unit ? unit.value : "kg");
              totalCp += safeParseFloat(cost ? cost.value : 0) * qtyKg;
              totalSp += safeParseFloat(sell ? sell.value : 0) * qtyKg;
            });
            var freight = safeParseFloat(freightEl ? freightEl.value : 0);
            totalCp += freight;
            if (totalCpEl) totalCpEl.value = totalCp.toFixed(2);
            if (totalSpEl) totalSpEl.value = totalSp.toFixed(2);
            if (plEl) plEl.value = (totalSp - totalCp).toFixed(2);
          } catch (e) {
            logError(e);
          }
        }

        // Cash totals
        function computeCashTotals() {
          try {
            var rows = qsa(".cash-row", itemsBodyCash);
            var totalCp = 0, totalSp = 0;
            rows.forEach(function (r) {
              var batches = safeParseFloat(qs('input[name="batches[]"]', r) ? qs('input[name="batches[]"]', r).value : 0);
              var cpPerBatch = safeParseFloat(qs('.cp-per-batch', r) ? qs('.cp-per-batch', r).value : 0);
              var spPerBatch = safeParseFloat(qs('.sp-per-batch', r) ? qs('.sp-per-batch', r).value : 0);
              totalCp += cpPerBatch * batches;
              totalSp += spPerBatch * batches;
            });
            var freight = safeParseFloat(freightEl ? freightEl.value : 0);
            totalCp += freight;
            if (totalCpEl) totalCpEl.value = totalCp.toFixed(2);
            if (totalSpEl) totalSpEl.value = totalSp.toFixed(2);
            if (plEl) plEl.value = (totalSp - totalCp).toFixed(2);
          } catch (e) {
            logError(e);
          }
        }

        // Create bill row (clone or build safe)
        function makeBillRow(q, unit, cost, sell) {
          q = q === undefined ? "" : q;
          unit = unit || "kg";
          cost = cost === undefined ? "" : cost;
          sell = sell === undefined ? "" : sell;
          var tr = document.createElement("tr");
          tr.className = "item-row";
          tr.innerHTML = "" +
            '<td><input name="quantity[]" class="form-control" value="' + (q) + '"></td>' +
            '<td><select name="unit[]" class="form-select">' +
            '<option value="kg"' + (unit === "kg" ? " selected" : "") + '>kg</option>' +
            '<option value="ton"' + (unit === "ton" ? " selected" : "") + '>ton</option>' +
            '</select></td>' +
            '<td><input name="cost_rate[]" class="form-control" value="' + (cost) + '"></td>' +
            '<td><input name="sell_rate[]" class="form-control" value="' + (sell) + '"></td>' +
            '<td><button type="button" class="btn btn-sm btn-danger remove-row">−</button></td>';
          itemsBodyBill.appendChild(tr);
          qsa('input,select', tr).forEach(function (el) { el.addEventListener('input', computeBillTotals); });
          var rem = qs('.remove-row', tr);
          if (rem) rem.addEventListener('click', function () { tr.remove(); computeBillTotals(); });
          return tr;
        }

        // Create cash row
        function makeCashRow(bt_id, batches, cp, sp) {
          try {
            bt_id = bt_id || "";
            batches = batches || 1;
            cp = cp === undefined ? "" : cp;
            sp = sp === undefined ? "" : sp;
            var tr = document.createElement("tr");
            tr.className = "cash-row";

            // copy template select if exists
            var template = qs('.bottle-type-select');
            var selectNode = null;
            if (template) {
              selectNode = template.cloneNode(true);
              selectNode.name = 'bottle_type_id[]';
              try { selectNode.value = bt_id; } catch (e) { /* ignore */ }
            } else {
              // fallback: create a basic select
              selectNode = document.createElement("select");
              selectNode.name = 'bottle_type_id[]';
              selectNode.className = 'form-select';
            }

            tr.innerHTML = "" +
              '<td class="select-cell"></td>' +
              '<td><input name="batches[]" class="form-control" value="' + batches + '"></td>' +
              '<td><input class="form-control cp-per-batch" readonly value="' + cp + '"></td>' +
              '<td><input class="form-control sp-per-batch" name="sp_batch[]" value="' + sp + '"></td>' +
              '<td><button type="button" class="btn btn-sm btn-danger remove-cash-row">−</button></td>';
            var cell = qs('.select-cell', tr);
            if (cell) cell.appendChild(selectNode);
            itemsBodyCash.appendChild(tr);
            var spBatchEl = qs('.sp-per-batch', tr);
            if (spBatchEl) spBatchEl.addEventListener('input', computeCashTotals);

            // init cp/sp from selected option if available
            var initOpt = selectNode.options ? selectNode.options[selectNode.selectedIndex] : null;
            if (initOpt) {
              var cpVal = initOpt.getAttribute('data-cp') || '';
              var spVal = initOpt.getAttribute('data-sp') || '';
              var cpEl = qs('.cp-per-batch', tr);
              var spEl = qs('.sp-per-batch', tr);
              if (cpEl && !cpEl.value) cpEl.value = cpVal;
              if (spEl && !spEl.value) spEl.value = spVal;
            }

            // listeners
            if (selectNode) selectNode.addEventListener('change', function () {
              var opt = selectNode.options[selectNode.selectedIndex];
              var cpVal = opt ? opt.getAttribute('data-cp') || '' : '';
              var spVal = opt ? opt.getAttribute('data-sp') || '' : '';
              var cpEl = qs('.cp-per-batch', tr);
              var spEl = qs('.sp-per-batch', tr);
              if (cpEl) cpEl.value = cpVal;
              if (spEl && !spEl.value) spEl.value = spVal;
              computeCashTotals();
            });

            var batchesEl = qs('input[name="batches[]"]', tr);
            if (batchesEl) batchesEl.addEventListener('input', computeCashTotals);
            var rem = qs('.remove-cash-row', tr);
            if (rem) rem.addEventListener('click', function () { tr.remove(); computeCashTotals(); });

            return tr;
          } catch (e) {
            logError(e);
            return null;
          }
        }

        // Mode toggle
        function showMode(mode) {
          try {
            if (mode === 'cash') {
                billModeEl.style.display = 'none';
                billModeEl.querySelectorAll('input, select').forEach(el => el.removeAttribute('required'));
                cashModeEl.style.display = '';
                cashModeEl.querySelectorAll('input, select').forEach(el => {
                  if (el.name) el.setAttribute('required', 'required');
                });
            } else {
                cashModeEl.style.display = 'none';
                cashModeEl.querySelectorAll('input, select').forEach(el => el.removeAttribute('required'));
                billModeEl.style.display = '';
                billModeEl.querySelectorAll('input, select').forEach(el => {
                  if (el.name) el.setAttribute('required', 'required');
                });
            }
            computeAll();
          } catch (e) { logError(e); }
        }

        if (saleTypeEl) saleTypeEl.addEventListener('change', function () { showMode(saleTypeEl.value); });

        // wire existing bill rows
        qsa('.item-row', itemsBodyBill).forEach(function (r) {
          qsa('input,select', r).forEach(function (el) { el.addEventListener('input', computeBillTotals); });
          var rem = qs('.remove-row', r);
          if (rem) rem.addEventListener('click', function () { r.remove(); computeBillTotals(); });
        });

        // bill add
        if (addRowBillBtn) addRowBillBtn.addEventListener('click', function () { makeBillRow('', 'kg', '', ''); computeBillTotals(); });

        // wire existing cash rows selects
        qsa('.bottle-type-select').forEach(function (sel) {
          try {
            var tr = sel.closest('tr');
            var opt = sel.options[sel.selectedIndex];
            if (opt) {
              var cpVal = opt.getAttribute('data-cp') || '';
              var spVal = opt.getAttribute('data-sp') || '';
              var cpEl = qs('.cp-per-batch', tr);
              var spEl = qs('.sp-per-batch', tr);
              if (cpEl && !cpEl.value) cpEl.value = cpVal;
              if (spEl && !spEl.value) spEl.value = spVal;
            }
            sel.addEventListener('change', function () {
              var opt2 = sel.options[sel.selectedIndex];
              var cpVal2 = opt2 ? opt2.getAttribute('data-cp') || '' : '';
              var spVal2 = opt2 ? opt2.getAttribute('data-sp') || '' : '';
              var cpEl2 = qs('.cp-per-batch', sel.closest('tr'));
              var spEl2 = qs('.sp-per-batch', sel.closest('tr'));
              if (cpEl2) cpEl2.value = cpVal2;
              if (spEl2 && !spEl2.value) spEl2.value = spVal2;
              computeCashTotals();
            });
          } catch (e) {
            logError(e);
          }
        });

        qsa('.remove-cash-row').forEach(function (btn) {
          btn.addEventListener('click', function (e) { e.target.closest('tr').remove(); computeCashTotals(); });
        });
        if (addRowCashBtn) addRowCashBtn.addEventListener('click', function () { makeCashRow('', 1, '', ''); computeCashTotals(); });

        if (freightEl) freightEl.addEventListener('input', computeAll);

        function computeAll() {
          if (saleTypeEl && saleTypeEl.value === 'cash') computeCashTotals();
          else computeBillTotals();
        }

        // initial mode: trust server-side sale_type if present, otherwise default to 'bill'
        var initialMode = (saleTypeEl && saleTypeEl.value && saleTypeEl.value.trim()) ? saleTypeEl.value : 'bill';
        showMode(initialMode);

        // initial totals calc
        computeAll();

      } catch (err) {
        logError(err);
      }
    });
  } catch (err) {
    logError(err);
  }
})();


// quick-submit-debug (append to sales.js)
(function () {
  try {
    var form = document.getElementById('sale-form');
    var saveBtn = document.getElementById('save-btn');
    if (form) {
      form.addEventListener('submit', function (ev) {
        console.log('DEBUG: form submit event fired. form data preview:');
        try {
          var fd = new FormData(form);
          var pairs = [];
          fd.forEach(function (v, k) { pairs.push(k + "=" + v); });
          console.log(pairs.slice(0, 40)); // print first 40 k=v for brevity
        } catch (e) {
          console.log('DEBUG: formdata error', e);
        }
        // allow the submit to proceed normally
      }, {passive: true});
    }
    if (saveBtn) {
      saveBtn.addEventListener('click', function () { console.log('DEBUG: Save button clicked'); });
    }
  } catch (err) {
    console.error('DEBUG submit logger error', err);
  }
})();
