(() => {
  const esc = (v) =>
    String(v ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const inr = (n) => '₹' + Number(n || 0).toLocaleString('en-IN');

  async function api(method, args = {}, isPost = false) {
    const res = await frappe.call({
      method: `kesari_jefs.api.${method}`,
      args,
      type: isPost ? 'POST' : 'GET',
    });
    return res.message;
  }

  async function apiUpload(method, formData) {
    const resp = await fetch(`/api/method/kesari_jefs.api.${method}`, {
      method: 'POST',
      headers: { 'X-Frappe-CSRF-Token': frappe.csrf_token },
      body: formData,
    });
    const json = await resp.json();
    if (!resp.ok || json.exc) {
      let msg = json._server_messages ? JSON.parse(JSON.parse(json._server_messages)[0]).message : json.exception || 'Upload failed';
      throw new Error(msg.replace(/<[^>]+>/g, ''));
    }
    return json.message;
  }

  function showErr(e) {
    frappe.msgprint({ title: __('Error'), indicator: 'red', message: esc(e.message || e) });
  }

  // Shared state across Desk pages
  const deskState = {
    activeBatchByFeed: {},
    activeFnf: null,
    activeRevision: null,
    settingsTab: 'company',
  };

  async function renderDashboard(root) {
    const boot = await api('get_bootstrap');
    const s = boot.stats;
    const feedRows = ['EMPLOYEE', 'SALARY', 'BONUS', 'LEAVE'].map((f) => {
      const b = boot.last_uploads[f];
      const route = f === 'EMPLOYEE' ? 'jefs-upload-employees' : f === 'SALARY' ? 'jefs-upload-salary' : f === 'BONUS' ? 'jefs-upload-bonus' : 'jefs-upload-leave';
      return `<tr>
        <td><b>${f}</b></td>
        <td>${b ? esc(b.file_name) : '<span class="jefs-muted">Not uploaded yet</span>'}</td>
        <td>${b ? b.ok_rows : '-'}</td>
        <td>${b ? esc(b.uploaded_by) : '-'}</td>
        <td><button class="btn btn-xs btn-default" onclick="frappe.set_route('${route}')">Upload</button></td>
      </tr>`;
    }).join('');

    const siteRows = (boot.site_rules || []).map((r) => `
      <tr>
        <td><b>${esc(r.site_code)}</b></td>
        <td>${esc(r.site_name)}</td>
        <td>${r.include_bonus ? '<span class="jefs-pill jefs-ok">Yes</span>' : '<span class="jefs-pill jefs-neutral">No</span>'}</td>
        <td>${r.include_leave ? '<span class="jefs-pill jefs-ok">Yes</span>' : '<span class="jefs-pill jefs-neutral">No</span>'}</td>
        <td>${r.include_gratuity ? '<span class="jefs-pill jefs-ok">Yes</span>' : '<span class="jefs-pill jefs-neutral">No</span>'}</td>
      </tr>`).join('');

    root.html(`
      <div class="jefs-desk-wrap">
        ${s.overdue_fnf > 0 ? `<div class="jefs-banner err"><b>Attention:</b> ${s.overdue_fnf} exit(s) exceeded the 2-working-day F&amp;F payment deadline!</div>` : ''}
        <div class="jefs-grid-4">
          <div class="jefs-card"><div class="jefs-muted">Active Employees</div><div class="jefs-stat">${s.active_employees}</div><div class="jefs-muted">Joiners this month: ${s.joiners_this_month}</div></div>
          <div class="jefs-card"><div class="jefs-muted">Exits Pending F&amp;F</div><div class="jefs-stat">${s.pending_fnf}</div><div class="jefs-muted">Overdue (&gt;2 working days): <b>${s.overdue_fnf}</b></div></div>
          <div class="jefs-card"><div class="jefs-muted">F&amp;F Awaiting Approval</div><div class="jefs-stat">${s.awaiting_approval}</div><div class="jefs-muted">Maker-checker queue</div></div>
          <div class="jefs-card"><div class="jefs-muted">Documents Generated</div><div class="jefs-stat">${s.docs_generated}</div><div class="jefs-muted">Missing data: ${s.missing_data_count}</div></div>
        </div>
        <div class="jefs-card">
          <h3>Quick Addons</h3>
          <div style="display:flex;gap:8px;flex-wrap:wrap;">
            <button class="btn btn-sm btn-primary" onclick="frappe.set_route('jefs-upload-employees')">1. Employees Excel</button>
            <button class="btn btn-sm btn-primary" onclick="frappe.set_route('jefs-upload-salary')">2. Salary Excel</button>
            <button class="btn btn-sm btn-primary" onclick="frappe.set_route('jefs-upload-bonus')">3. Bonus Report</button>
            <button class="btn btn-sm btn-primary" onclick="frappe.set_route('jefs-upload-leave')">4. Leave Report</button>
            <button class="btn btn-sm btn-default" onclick="frappe.set_route('jefs-joining-kit')">Joining Kit &amp; Police</button>
            <button class="btn btn-sm btn-default" onclick="frappe.set_route('jefs-fnf')">Exits &amp; F&amp;F</button>
            <button class="btn btn-sm btn-default" onclick="frappe.set_route('jefs-service-certificates')">Service Certificates</button>
            <button class="btn btn-sm btn-default" onclick="frappe.set_route('jefs-wage-revision')">Min Wages &amp; Increment Letters</button>
            <button class="btn btn-sm btn-default" onclick="frappe.set_route('jefs-documents-register')">Documents Register</button>
            <button class="btn btn-sm btn-default" onclick="frappe.set_route('List', 'Full and Final Statement')">HRMS F&amp;F Statements</button>
            <button class="btn btn-sm btn-default" id="jefs-sync-hrms">Sync &harr; HR Records</button>
          </div>
        </div>
        <div class="jefs-grid-2">
          <div class="jefs-card">
            <h3>4 Excel Data Feeds</h3>
            <div class="jefs-table-wrap"><table class="jefs-table"><thead><tr><th>Feed</th><th>Last File</th><th>Rows</th><th>By</th><th></th></tr></thead><tbody>${feedRows}</tbody></table></div>
          </div>
          <div class="jefs-card">
            <h3>Client Site F&amp;F Rules</h3>
            <div class="jefs-table-wrap"><table class="jefs-table"><thead><tr><th>Site</th><th>Principal Employer</th><th>Bonus</th><th>Leave</th><th>Gratuity</th></tr></thead><tbody>${siteRows}</tbody></table></div>
          </div>
        </div>
      </div>
    `);
    root.find('#jefs-sync-hrms').on('click', async () => {
      try {
        const res = await api('sync_all_with_hrms', {}, true);
        frappe.show_alert({ message: `Synced Employees: ${res.employees}, Salaries: ${res.salaries}, Leaves: ${res.leaves}, F&F: ${res.fnf_statements}`, indicator: 'green' });
        renderDashboard(root);
      } catch (e) { showErr(e); }
    });
  }

  async function renderUploadFeed(root, feed) {
    const meta = {
      EMPLOYEE: { title: 'Employees Excel Upload', desc: 'Master employee database: personal details, Aadhaar/PAN, bank, designation, client site, DOJ, exit dates & nominees.', extra: '' },
      SALARY: { title: 'Salary Excel Upload', desc: 'Monthly wage structure: Basic, DA/VDA, HRA, allowances, PF/ESI/PT deductions, Days in month & Paid days.', extra: '<div><label>Salary Period (YYYY-MM)</label><input type="text" class="form-control" id="u-period" value="2027-01" /></div>' },
      BONUS: { title: 'Bonus Report Upload', desc: 'Historical & current FY bonus eligibility, payable working days, bonus wage, and bonus already paid.', extra: '<div><label>Financial Year</label><input type="text" class="form-control" id="u-fy" value="2026-27" /></div>' },
      LEAVE: { title: 'Leave Report Upload', desc: 'Accrued Earned Leave (EL) balances, opening/accrued/taken/encashed records for F&F leave encashment.', extra: '' },
      PHOTOS: { title: 'Employee Photos ZIP Upload', desc: 'Upload a .zip containing employee photos named by employee code (e.g. KM1023.jpg) for Form 18 ID Cards.', extra: '' },
    }[feed];

    const batches = (await api('list_upload_batches')).filter((b) => feed === 'PHOTOS' || b.feed === feed);

    if (feed === 'PHOTOS') {
      root.html(`
        <div class="jefs-desk-wrap">
          <div class="jefs-card">
            <h3>${meta.title}</h3>
            <p class="jefs-muted">${meta.desc}</p>
            <div style="display:flex;gap:10px;align-items:center;flex-wrap:wrap;">
              <input type="file" id="u-photo-zip" accept=".zip" class="form-control" style="max-width:360px;" />
              <button class="btn btn-primary" id="u-photo-btn">Upload Photos ZIP</button>
            </div>
            <div id="u-photo-res" style="margin-top:10px;"></div>
          </div>
        </div>
      `);
      root.find('#u-photo-btn').on('click', async () => {
        const inp = root.find('#u-photo-zip')[0];
        if (!inp.files.length) return frappe.msgprint('Choose a .zip file first');
        const fd = new FormData();
        fd.append('file', inp.files[0]);
        try {
          const r = await apiUpload('upload_photos_zip', fd);
          root.find('#u-photo-res').html(`<div class="jefs-banner ok">Matched ${r.matched.length} photo(s): ${esc(r.matched.join(', '))}. Unmatched: ${r.unmatched.length}</div>`);
        } catch (e) { showErr(e); }
      });
      return;
    }

    const active = deskState.activeBatchByFeed[feed];
    let wizardHtml = '';
    if (active) {
      const mapRows = active.headers.map((h) => `
        <tr>
          <td><b>${esc(h)}</b></td>
          <td>
            <select class="form-control u-map-sel" data-col="${esc(h)}">
              <option value="">-- Ignore --</option>
              ${active.system_fields.map((sf) => `<option value="${sf}" ${active.mapping[h] === sf ? 'selected' : ''}>${sf}</option>`).join('')}
            </select>
          </td>
        </tr>`).join('');
      const errRows = (active.preview_errors || []).map((e) => `<tr><td>${e.row_num}</td><td style="color:#991b1b">${esc(e.errors)}</td><td class="jefs-mono">${esc(JSON.stringify(e.raw).slice(0, 140))}</td></tr>`).join('');
      const okRows = (active.preview_valid || []).slice(0, 10).map((r) => `<tr><td>${r.__row_num}</td><td><b>${esc(r.employee_code)}</b></td><td class="jefs-mono">${esc(JSON.stringify(r).slice(0, 140))}</td></tr>`).join('');

      wizardHtml = `
        <div class="jefs-card" style="border-color:#2563eb;">
          <h3>Validation Preview: ${esc(active.batch_id)} (${esc(active.file_name)})</h3>
          <div style="display:flex;gap:8px;flex-wrap:wrap;margin-bottom:10px;">
            <span class="jefs-pill jefs-neutral">Total: ${active.total_rows}</span>
            <span class="jefs-pill jefs-ok">Valid: ${active.ok_rows}</span>
            <span class="jefs-pill ${active.error_rows ? 'jefs-err' : 'jefs-ok'}">Errors: ${active.error_rows}</span>
            ${active.missing_required.length ? `<span class="jefs-pill jefs-err">Unmapped required: ${esc(active.missing_required.join(', '))}</span>` : ''}
          </div>
          <details style="margin-bottom:10px;">
            <summary style="cursor:pointer;font-weight:600;">Column Mapping (saved automatically for ${feed})</summary>
            <div class="jefs-table-wrap" style="margin-top:8px;"><table class="jefs-table"><thead><tr><th>Excel Column</th><th>System Field</th></tr></thead><tbody>${mapRows}</tbody></table></div>
            <button class="btn btn-sm btn-default" id="u-apply-map" style="margin-top:8px;">Apply &amp; Re-validate</button>
          </details>
          ${errRows ? `<h4>Row Errors</h4><div class="jefs-table-wrap" style="max-height:220px;overflow:auto;"><table class="jefs-table"><thead><tr><th>Row</th><th>Errors</th><th>Raw</th></tr></thead><tbody>${errRows}</tbody></table></div>` : ''}
          ${okRows ? `<h4 style="margin-top:10px;">Valid Preview</h4><div class="jefs-table-wrap" style="max-height:220px;overflow:auto;"><table class="jefs-table"><thead><tr><th>Row</th><th>Emp Code</th><th>Parsed</th></tr></thead><tbody>${okRows}</tbody></table></div>` : ''}
          <div style="display:flex;gap:8px;margin-top:12px;flex-wrap:wrap;">
            <button class="btn btn-primary" id="u-commit" ${active.ok_rows === 0 || active.missing_required.length ? 'disabled' : ''}>Commit ${active.ok_rows} Valid Row(s)</button>
            ${active.error_rows ? `<a class="btn btn-default" href="/api/method/kesari_jefs.api.download_batch_errors?batch_id=${encodeURIComponent(active.batch_id)}">Download Error Report (.xlsx)</a>` : ''}
            <button class="btn btn-danger" id="u-discard">Discard</button>
          </div>
        </div>`;
    }

    const batchRows = batches.map((b) => `
      <tr>
        <td class="jefs-mono">${esc(b.name)}</td>
        <td>${esc(b.file_name)}</td>
        <td>${b.ok_rows}/${b.total_rows} (${b.error_rows} err)</td>
        <td><span class="jefs-pill ${b.status === 'COMMITTED' ? 'jefs-ok' : b.status === 'DISCARDED' ? 'jefs-err' : 'jefs-warn'}">${esc(b.status)}</span></td>
        <td>${esc(b.uploaded_by)}</td>
        <td>${esc(String(b.committed_at || b.creation).slice(0, 16))}</td>
      </tr>`).join('');

    root.html(`
      <div class="jefs-desk-wrap">
        <div class="jefs-card">
          <h3>${meta.title}</h3>
          <p class="jefs-muted">${meta.desc}</p>
          <div class="jefs-form-row">
            ${meta.extra}
            <div><label>Select Excel / CSV (.xlsx, .xls, .csv)</label><input type="file" id="u-file" accept=".xlsx,.xls,.csv" class="form-control" /></div>
          </div>
          <div style="display:flex;gap:8px;flex-wrap:wrap;">
            <button class="btn btn-primary" id="u-btn">Upload &amp; Validate</button>
            <a class="btn btn-default" href="/api/method/kesari_jefs.api.download_sample_template?feed=${feed}">Download Sample ${feed} .xlsx</a>
          </div>
        </div>
        ${wizardHtml}
        <div class="jefs-card">
          <h3>${feed} Upload History</h3>
          <div class="jefs-table-wrap"><table class="jefs-table"><thead><tr><th>Batch</th><th>File</th><th>Rows</th><th>Status</th><th>Uploaded By</th><th>Time</th></tr></thead><tbody>${batchRows || '<tr><td colspan="6" class="jefs-muted">No batches uploaded yet.</td></tr>'}</tbody></table></div>
        </div>
      </div>
    `);

    root.find('#u-btn').on('click', async () => {
      const inp = root.find('#u-file')[0];
      if (!inp.files.length) return frappe.msgprint('Choose an Excel/CSV file first');
      const fd = new FormData();
      fd.append('feed', feed);
      fd.append('file', inp.files[0]);
      if (feed === 'SALARY') fd.append('period', root.find('#u-period').val() || '');
      if (feed === 'BONUS') fd.append('fy', root.find('#u-fy').val() || '');
      try {
        deskState.activeBatchByFeed[feed] = await apiUpload('upload_feed_file', fd);
        frappe.show_alert({ message: `Validated ${deskState.activeBatchByFeed[feed].total_rows} row(s)`, indicator: 'green' });
        renderUploadFeed(root, feed);
      } catch (e) { showErr(e); }
    });

    if (active) {
      root.find('#u-apply-map').on('click', async () => {
        const map = {};
        root.find('.u-map-sel').each((_, el) => { map[el.dataset.col] = el.value; });
        try {
          const upd = await api('update_batch_mapping', { batch_id: active.batch_id, mapping_json: JSON.stringify(map) }, true);
          deskState.activeBatchByFeed[feed] = { ...active, ...upd };
          frappe.show_alert({ message: 'Mapping saved & re-validated', indicator: 'blue' });
          renderUploadFeed(root, feed);
        } catch (e) { showErr(e); }
      });
      root.find('#u-commit').on('click', async () => {
        try {
          const res = await api('commit_batch', { batch_id: active.batch_id }, true);
          deskState.activeBatchByFeed[feed] = null;
          frappe.show_alert({ message: `Committed: ${res.inserted} inserted, ${res.updated} updated`, indicator: 'green' });
          renderUploadFeed(root, feed);
        } catch (e) { showErr(e); }
      });
      root.find('#u-discard').on('click', async () => {
        try {
          await api('discard_batch', { batch_id: active.batch_id }, true);
          deskState.activeBatchByFeed[feed] = null;
          renderUploadFeed(root, feed);
        } catch (e) { showErr(e); }
      });
    }
  }

  async function renderJoiningKit(root) {
    const emps = await api('list_employees', {});
    const badge = (info) => info.ready
      ? '<span class="jefs-pill jefs-ok">✓ Ready</span>'
      : `<span class="jefs-pill jefs-err" title="${esc(info.missing.join(', '))}">✗ ${esc(info.missing[0])}</span>`;

    const rows = emps.map((e) => `
      <tr>
        <td><input type="checkbox" class="jk-emp" value="${esc(e.employee_code)}" checked /></td>
        <td><b>${esc(e.employee_code)}</b><br/><span class="jefs-muted">${esc(e.full_name)} · ${esc(e.client_site)}</span></td>
        <td>${badge(e.readiness.OFFER_LETTER)}</td>
        <td>${badge(e.readiness.APPOINTMENT_LETTER)}</td>
        <td>${badge(e.readiness.GRATUITY_FORM_F)}</td>
        <td>${badge(e.readiness.ID_CARD)}</td>
        <td>${badge(e.readiness.EPFO_FORM_2)}</td>
        <td>${badge(e.readiness.POLICE_VERIFICATION)}</td>
      </tr>`).join('');

    root.html(`
      <div class="jefs-desk-wrap">
        <div class="jefs-card">
          <h3>Joining Kit (5 Docs) &amp; Police Verification Letter</h3>
          <div style="display:flex;gap:12px;flex-wrap:wrap;align-items:center;margin-bottom:12px;">
            <label><input type="checkbox" class="jk-doc" value="OFFER_LETTER" checked /> Offer Letter</label>
            <label><input type="checkbox" class="jk-doc" value="APPOINTMENT_LETTER" checked /> Appointment Letter</label>
            <label><input type="checkbox" class="jk-doc" value="GRATUITY_FORM_F" checked /> Gratuity Form IV/F</label>
            <label><input type="checkbox" class="jk-doc" value="ID_CARD" checked /> ID Card (Form 18)</label>
            <label><input type="checkbox" class="jk-doc" value="EPFO_FORM_2" checked /> EPFO Form 11/2</label>
            <label><input type="checkbox" class="jk-doc" value="POLICE_VERIFICATION" checked /> Police Verification</label>
            <button class="btn btn-primary" id="jk-gen">Generate Kit &amp; Download ZIP</button>
            <button class="btn btn-default" id="jk-sheet">Generate A4 ID Card Sheet</button>
          </div>
          <div id="jk-res"></div>
          <div class="jefs-table-wrap"><table class="jefs-table"><thead><tr><th>Sel</th><th>Employee</th><th>Offer</th><th>Appt</th><th>Form IV/F</th><th>ID Card</th><th>EPFO</th><th>Police</th></tr></thead><tbody>${rows || '<tr><td colspan="8" class="jefs-muted">Upload Employee Excel first.</td></tr>'}</tbody></table></div>
        </div>
      </div>
    `);

    root.find('#jk-gen').on('click', async () => {
      const codes = root.find('.jk-emp:checked').map((_, c) => c.value).get();
      const docs = root.find('.jk-doc:checked').map((_, c) => c.value).get();
      if (!codes.length || !docs.length) return frappe.msgprint('Select employees and document types');
      try {
        frappe.show_alert({ message: 'Generating PDFs via Gotenberg...', indicator: 'blue' });
        const r = await api('generate_documents', { employee_codes_json: JSON.stringify(codes), doc_types_json: JSON.stringify(docs), merge_kit: 1 }, true);
        root.find('#jk-res').html(`
          <div class="jefs-banner ok">
            Generated <b>${r.generated.length}</b> PDF(s), Skipped <b>${r.skipped.length}</b>.
            ${r.zip_token ? `<a class="btn btn-xs btn-primary" style="margin-left:10px;" href="/api/method/kesari_jefs.api.download_generated_artifact?token=${encodeURIComponent(r.zip_token)}">Download Joining Kit ZIP</a>` : ''}
            ${r.skipped.length ? `<div class="jefs-muted" style="margin-top:6px;">Skipped: ${esc(r.skipped.map((s) => `${s.employee_code} ${s.doc_type}: ${s.reason}`).join(' | '))}</div>` : ''}
          </div>`);
      } catch (e) { showErr(e); }
    });

    root.find('#jk-sheet').on('click', async () => {
      const codes = root.find('.jk-emp:checked').map((_, c) => c.value).get();
      if (!codes.length) return frappe.msgprint('Select employees first');
      try {
        const r = await api('generate_id_card_sheet', { employee_codes_json: JSON.stringify(codes) }, true);
        window.open(`/api/method/kesari_jefs.api.download_generated_artifact?token=${encodeURIComponent(r.file_token)}`, '_blank');
      } catch (e) { showErr(e); }
    });
  }

  async function renderFnF(root) {
    const data = await api('list_fnf_settlements');
    const rows = data.settlements.map((f) => `
      <tr>
        <td class="jefs-mono">${esc(f.name)}</td>
        <td><b>${esc(f.employee_code)}</b> · ${esc(f.employee_name)}</td>
        <td>v${f.version}</td>
        <td><span class="jefs-pill ${f.status === 'APPROVED' ? 'jefs-ok' : f.status === 'SUBMITTED' ? 'jefs-warn' : 'jefs-neutral'}">${esc(f.status)}</span></td>
        <td>${esc(f.payment_due_date)} ${f.is_overdue && f.status !== 'APPROVED' ? '<span class="jefs-pill jefs-err">Overdue</span>' : ''}</td>
        <td class="num"><b>${inr(f.net_payable_rupees)}</b></td>
        <td>
          <button class="btn btn-xs btn-primary fnf-open" data-id="${esc(f.name)}">Open</button>
          ${f.hrms_fnf_statement ? `<button class="btn btn-xs btn-default" onclick="frappe.set_route('Form', 'Full and Final Statement', '${esc(f.hrms_fnf_statement)}')">HRMS F&amp;F</button>` : ''}
        </td>
      </tr>`).join('');

    const uninit = data.uninitiated_exits.map((u) => `
      <tr>
        <td><b>${esc(u.employee_code)}</b> · ${esc(u.full_name)}</td>
        <td>${esc(u.date_of_exit)}</td>
        <td>${esc(u.client_site)}</td>
        <td><button class="btn btn-xs btn-primary fnf-init" data-code="${esc(u.employee_code)}">Initiate F&amp;F</button></td>
      </tr>`).join('');

    let detailHtml = '';
    if (deskState.activeFnf) {
      const d = deskState.activeFnf;
      const f = d.fnf;
      const lines = (f.lines || []).map((l) => `
        <tr>
          <td><span class="jefs-pill ${l.line_type === 'EARNING' ? 'jefs-ok' : 'jefs-err'}">${l.line_type}</span> ${esc(l.label)}</td>
          <td class="jefs-mono">${esc(l.formula_text)}</td>
          <td class="num"><b>${inr(l.amount_rupees)}</b></td>
          <td>${l.is_manual && f.status === 'DRAFT' ? `<button class="btn btn-xs btn-danger fnf-del-line" data-id="${f.name}" data-line="${l.name}">✕</button>` : ''}</td>
        </tr>`).join('');
      const docsHtml = (d.documents || []).map((doc) => `<a class="btn btn-xs btn-default" href="/api/method/kesari_jefs.api.download_document?doc_id=${encodeURIComponent(doc.name)}">${esc(doc.doc_type)} (${esc(doc.ref_no)})</a>`).join(' ');

      detailHtml = `
        <div class="jefs-card" style="border-color:#2563eb;">
          <div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:10px;margin-bottom:10px;">
            <div>
              <h3>${esc(f.employee_name)} (${esc(f.employee_code)}) — ${esc(f.name)} v${f.version}</h3>
              <div class="jefs-muted">Tenure: <b>${esc(f.tenure_display)}</b> (Counted: ${f.counted_years} yrs) · Site: ${esc(f.client_site)} · Due: ${esc(f.payment_due_date)}</div>
            </div>
            <div style="text-align:right;">
              <div class="jefs-muted">Net Payable</div>
              <div style="font-size:24px;font-weight:800;">${inr(f.net_payable_rupees)}</div>
              <div class="jefs-muted">${esc(d.net_words)}</div>
            </div>
          </div>
          ${d.errors.length ? `<div class="jefs-banner err">${esc(d.errors.join(' | '))}</div>` : ''}
          ${d.warnings.length ? `<div class="jefs-banner warn">${esc(d.warnings.join(' | '))}</div>` : ''}
          ${f.status === 'APPROVED' ? `<div class="jefs-banner ok">Approved &amp; Locked by ${esc(f.approved_by)}. Service Certificate generated! ${docsHtml}</div>` : ''}
          <div class="jefs-table-wrap"><table class="jefs-table"><thead><tr><th>Component</th><th>Formula</th><th class="num">Amount</th><th></th></tr></thead><tbody>${lines}</tbody></table></div>
          ${f.status === 'DRAFT' ? `
            <div class="jefs-form-row" style="margin-top:12px;">
              <div><label>Code</label><select class="form-control" id="ml-code"><option>ARREARS</option><option>NOTICE_RECOVERY</option><option>ADVANCE</option><option>OTHER</option></select></div>
              <div><label>Type</label><select class="form-control" id="ml-type"><option>EARNING</option><option>DEDUCTION</option></select></div>
              <div><label>Amount (₹)</label><input type="number" class="form-control" id="ml-amt" value="500" /></div>
              <div><label>Note</label><input type="text" class="form-control" id="ml-note" placeholder="Uniform / arrears" /></div>
              <div style="display:flex;align-items:flex-end;"><button class="btn btn-default" id="fnf-add-line" data-id="${f.name}">+ Add Line</button></div>
            </div>` : ''}
          <div style="display:flex;gap:8px;margin-top:12px;flex-wrap:wrap;">
            ${f.status === 'DRAFT' ? `<button class="btn btn-default" id="fnf-recalc" data-id="${f.name}">Recalculate</button><button class="btn btn-primary" id="fnf-sub" data-id="${f.name}">Submit for Approval</button>` : ''}
            ${f.status === 'SUBMITTED' ? `<button class="btn btn-primary" id="fnf-app" data-id="${f.name}">Approve &amp; Lock (+ Service Cert)</button><button class="btn btn-danger" id="fnf-rej" data-id="${f.name}">Reject to Draft</button>` : ''}
            ${f.status === 'APPROVED' ? `<button class="btn btn-default" id="fnf-rev" data-id="${f.name}">Create Revision</button>` : ''}
          </div>
        </div>`;
    }

    root.html(`
      <div class="jefs-desk-wrap">
        <div style="margin-bottom:10px;display:flex;gap:8px;justify-content:flex-end;">
          <a class="btn btn-sm btn-default" href="/api/method/kesari_jefs.api.export_fnf_excel">Export Client F&amp;F Workbook (.xlsx)</a>
        </div>
        ${detailHtml}
        ${uninit ? `<div class="jefs-card"><h3>Exited Employees Pending F&amp;F</h3><table class="jefs-table"><thead><tr><th>Employee</th><th>Exit Date</th><th>Site</th><th></th></tr></thead><tbody>${uninit}</tbody></table></div>` : ''}
        <div class="jefs-card">
          <h3>Full &amp; Final Settlements</h3>
          <div class="jefs-table-wrap"><table class="jefs-table"><thead><tr><th>ID</th><th>Employee</th><th>Ver</th><th>Status</th><th>Due Date</th><th class="num">Net Payable</th><th></th></tr></thead><tbody>${rows || '<tr><td colspan="7" class="jefs-muted">No F&amp;F settlements yet.</td></tr>'}</tbody></table></div>
        </div>
      </div>
    `);

    root.find('.fnf-init').on('click', async function () { try { deskState.activeFnf = await api('initiate_fnf', { employee_code: this.dataset.code }, true); renderFnF(root); } catch (e) { showErr(e); } });
    root.find('.fnf-open').on('click', async function () { try { deskState.activeFnf = await api('get_fnf_detail', { fnf_id: this.dataset.id }); renderFnF(root); } catch (e) { showErr(e); } });
    root.find('#fnf-recalc').on('click', async function () { try { deskState.activeFnf = await api('recalculate_fnf', { fnf_id: this.dataset.id }, true); renderFnF(root); } catch (e) { showErr(e); } });
    root.find('#fnf-add-line').on('click', async function () {
      try {
        deskState.activeFnf = await api('add_fnf_manual_line', {
          fnf_id: this.dataset.id, code: root.find('#ml-code').val(), line_type: root.find('#ml-type').val(),
          amount_rupees: root.find('#ml-amt').val(), note: root.find('#ml-note').val(),
        }, true);
        renderFnF(root);
      } catch (e) { showErr(e); }
    });
    root.find('.fnf-del-line').on('click', async function () { try { deskState.activeFnf = await api('delete_fnf_manual_line', { fnf_id: this.dataset.id, line_name: this.dataset.line }, true); renderFnF(root); } catch (e) { showErr(e); } });
    root.find('#fnf-sub').on('click', async function () { try { deskState.activeFnf = await api('submit_fnf', { fnf_id: this.dataset.id }, true); frappe.show_alert({ message: 'Submitted for Approval', indicator: 'green' }); renderFnF(root); } catch (e) { showErr(e); } });
    root.find('#fnf-app').on('click', async function () { try { deskState.activeFnf = await api('approve_fnf', { fnf_id: this.dataset.id, remarks: 'Approved' }, true); frappe.show_alert({ message: 'Approved & Service Certificate generated', indicator: 'green' }); renderFnF(root); } catch (e) { showErr(e); } });
    root.find('#fnf-rej').on('click', async function () { try { deskState.activeFnf = await api('reject_fnf', { fnf_id: this.dataset.id, remarks: 'Returned' }, true); renderFnF(root); } catch (e) { showErr(e); } });
    root.find('#fnf-rev').on('click', async function () { try { deskState.activeFnf = await api('revise_fnf', { fnf_id: this.dataset.id }, true); renderFnF(root); } catch (e) { showErr(e); } });
  }

  async function renderServiceCertificates(root) {
    const docs = await api('list_documents', { doc_type: 'SERVICE_CERTIFICATE' });
    const rows = docs.map((d) => `
      <tr>
        <td class="jefs-mono"><b>${esc(d.ref_no)}</b></td>
        <td><b>${esc(d.employee_code)}</b> · ${esc(d.employee_name)}</td>
        <td>v${d.version}</td>
        <td>${esc(String(d.generated_at).slice(0, 16))}</td>
        <td>${d.is_void ? '<span class="jefs-pill jefs-err">VOID</span>' : '<span class="jefs-pill jefs-ok">Active</span>'}</td>
        <td>
          <a class="btn btn-xs btn-primary" href="/api/method/kesari_jefs.api.download_document?doc_id=${encodeURIComponent(d.name)}&fmt=pdf">PDF</a>
          <a class="btn btn-xs btn-default" href="/api/method/kesari_jefs.api.download_document?doc_id=${encodeURIComponent(d.name)}&fmt=docx">DOCX</a>
        </td>
      </tr>`).join('');
    root.html(`
      <div class="jefs-desk-wrap">
        <div class="jefs-card">
          <h3>Service Certificates</h3>
          <p class="jefs-muted">Auto-generated on company letterhead when F&amp;F settlement is Approved.</p>
          <div class="jefs-table-wrap"><table class="jefs-table"><thead><tr><th>Ref No</th><th>Employee</th><th>Ver</th><th>Generated</th><th>Status</th><th>Download</th></tr></thead><tbody>${rows || '<tr><td colspan="6" class="jefs-muted">No service certificates generated yet.</td></tr>'}</tbody></table></div>
        </div>
      </div>`);
  }

  async function renderWageRevision(root) {
    const [rates, revs, settings] = await Promise.all([api('list_min_wages'), api('list_wage_revisions'), api('get_settings_data')]);
    const rateRows = rates.map((r) => `<tr><td>${esc(r.state)}</td><td>${esc(r.zone)}</td><td>${esc(r.skill_category)}</td><td>${esc(r.effective_from)}</td><td class="num">${inr(Math.round(r.total_paise/100))}</td><td class="jefs-muted">${esc(r.source_reference)}</td></tr>`).join('');
    const revRows = revs.map((r) => `<tr><td class="jefs-mono">${esc(r.name)}</td><td><b>${esc(r.revision_name)}</b></td><td>${esc(r.effective_from)}</td><td>${esc(r.policy)}</td><td><span class="jefs-pill ${r.status==='APPROVED'?'jefs-ok':'jefs-warn'}">${esc(r.status)}</span></td><td><button class="btn btn-xs btn-primary wr-open" data-id="${esc(r.name)}">Open Grid</button></td></tr>`).join('');

    let revDetail = '';
    if (deskState.activeRevision) {
      const rv = deskState.activeRevision;
      const itemsHtml = (rv.items || []).map((it) => `
        <tr>
          <td><b>${esc(it.employee_code)}</b> · ${esc(it.employee_name)}</td>
          <td>${esc(it.skill_category)}</td>
          <td class="num">${inr(Math.round(it.old_total_paise/100))}</td>
          <td class="num">${inr(Math.round(it.min_wage_paise/100))}</td>
          <td class="num">${rv.status === 'DRAFT' ? `<input type="number" class="form-control wr-edit" data-rid="${rv.name}" data-iid="${it.name}" style="width:100px" value="${Math.round(it.proposed_total_paise/100)}" />` : inr(Math.round(it.proposed_total_paise/100))}</td>
          <td class="num">${inr(Math.round(it.delta_paise/100))}</td>
          <td>${it.needs_letter ? '<span class="jefs-pill jefs-ok">Yes</span>' : '<span class="jefs-pill jefs-neutral">No</span>'}</td>
          <td class="jefs-muted">${esc(it.reason)}</td>
        </tr>`).join('');
      revDetail = `
        <div class="jefs-card" style="border-color:#2563eb;">
          <h3>Revision Grid: ${esc(rv.revision_name)} (${esc(rv.status)})</h3>
          <div class="jefs-table-wrap"><table class="jefs-table"><thead><tr><th>Employee</th><th>Skill</th><th class="num">Old</th><th class="num">Min Wage</th><th class="num">Proposed</th><th class="num">Δ</th><th>Letter</th><th>Reason</th></tr></thead><tbody>${itemsHtml}</tbody></table></div>
          <div style="display:flex;gap:8px;margin-top:12px;">
            ${rv.status === 'DRAFT' ? `<button class="btn btn-primary" id="wr-approve" data-id="${rv.name}">Approve &amp; Generate Increment Letters</button>` : ''}
            <a class="btn btn-default" href="/api/method/kesari_jefs.api.export_wage_revision_excel?revision_id=${encodeURIComponent(rv.name)}">Export Revised Wages (.xlsx)</a>
          </div>
          <div id="wr-zip" style="margin-top:8px;"></div>
        </div>`;
    }

    const watcherRows = (settings.watcher_sources || []).map((w) => `<tr><td>${esc(w.state)}</td><td class="jefs-mono">${esc(w.url)}</td><td>${esc(w.last_status)}</td></tr>`).join('');

    root.html(`
      <div class="jefs-desk-wrap">
        ${revDetail}
        <div class="jefs-grid-2">
          <div class="jefs-card">
            <h3>Create Minimum Wage Revision Run</h3>
            <div class="jefs-form-row">
              <div><label>Name</label><input type="text" class="form-control" id="wr-name" value="April 2027 Revision" /></div>
              <div><label>Effective From</label><input type="date" class="form-control" id="wr-eff" value="2027-04-01" /></div>
              <div><label>Policy</label><select class="form-control" id="wr-pol"><option value="RAISE_TO_MIN">Raise to Minimum Only</option><option value="ADD_VDA_DELTA">Add VDA Delta to All</option><option value="CUSTOM_PCT">Custom %</option></select></div>
              <div><label>VDA Delta (₹) / %</label><input type="number" class="form-control" id="wr-val" value="0" /></div>
            </div>
            <button class="btn btn-primary" id="wr-create">Propose Revision</button>
            <h4 style="margin-top:14px;">Revision Runs</h4>
            <div class="jefs-table-wrap"><table class="jefs-table"><thead><tr><th>ID</th><th>Name</th><th>Eff</th><th>Policy</th><th>Status</th><th></th></tr></thead><tbody>${revRows || '<tr><td colspan="6" class="jefs-muted">None yet</td></tr>'}</tbody></table></div>
          </div>
          <div class="jefs-card">
            <h3>Minimum Wage Rates</h3>
            <div class="jefs-form-row">
              <div><label>State</label><input type="text" class="form-control" id="mw-st" value="Gujarat" /></div>
              <div><label>Zone</label><input type="text" class="form-control" id="mw-zn" value="Zone-A" /></div>
              <div><label>Skill</label><select class="form-control" id="mw-sk"><option>Unskilled</option><option>Semi-Skilled</option><option>Skilled</option><option>Highly Skilled</option></select></div>
              <div><label>Eff Date</label><input type="date" class="form-control" id="mw-eff" value="2027-04-01" /></div>
              <div><label>Basic (₹)</label><input type="number" class="form-control" id="mw-b" value="12500" /></div>
              <div><label>VDA (₹)</label><input type="number" class="form-control" id="mw-v" value="2500" /></div>
            </div>
            <button class="btn btn-sm btn-primary" id="mw-add">+ Add Rate</button>
            <div class="jefs-table-wrap" style="margin-top:10px;max-height:200px;overflow:auto;"><table class="jefs-table"><thead><tr><th>State</th><th>Zone</th><th>Skill</th><th>Eff</th><th class="num">Total</th><th>Source</th></tr></thead><tbody>${rateRows}</tbody></table></div>
            <h4 style="margin-top:12px;">Minimum Wage Notification Watcher</h4>
            <table class="jefs-table"><thead><tr><th>State</th><th>URL</th><th>Status</th></tr></thead><tbody>${watcherRows}</tbody></table>
            <button class="btn btn-xs btn-default" id="wr-watch" style="margin-top:6px;">Check Now</button>
          </div>
        </div>
      </div>`);

    root.find('#mw-add').on('click', async () => {
      try {
        await api('save_min_wage', {
          state: root.find('#mw-st').val(), zone: root.find('#mw-zn').val(), skill_category: root.find('#mw-sk').val(),
          effective_from: root.find('#mw-eff').val(), basic_rupees: root.find('#mw-b').val(), vda_rupees: root.find('#mw-v').val(),
          source_reference: 'Manual HR entry',
        }, true);
        renderWageRevision(root);
      } catch (e) { showErr(e); }
    });
    root.find('#wr-create').on('click', async () => {
      const pol = root.find('#wr-pol').val();
      const val = root.find('#wr-val').val();
      try {
        deskState.activeRevision = await api('create_wage_revision', {
          revision_name: root.find('#wr-name').val(), effective_from: root.find('#wr-eff').val(), policy: pol,
          vda_delta_rupees: pol === 'ADD_VDA_DELTA' ? val : 0, custom_pct: pol === 'CUSTOM_PCT' ? val : 0,
        }, true);
        renderWageRevision(root);
      } catch (e) { showErr(e); }
    });
    root.find('.wr-open').on('click', async function () { deskState.activeRevision = await api('get_wage_revision', { revision_id: this.dataset.id }); renderWageRevision(root); });
    root.find('.wr-edit').on('change', async function () {
      try {
        deskState.activeRevision = await api('update_revision_item', { revision_id: this.dataset.rid, item_name: this.dataset.iid, proposed_rupees: this.value }, true);
        renderWageRevision(root);
      } catch (e) { showErr(e); }
    });
    root.find('#wr-approve').on('click', async function () {
      try {
        const res = await api('approve_wage_revision', { revision_id: this.dataset.id }, true);
        deskState.activeRevision = res.revision;
        frappe.show_alert({ message: `Approved & generated ${res.generated.length} Increment Letter(s)`, indicator: 'green' });
        await renderWageRevision(root);
        if (res.zip_token) {
          root.find('#wr-zip').html(`<a class="btn btn-sm btn-primary" href="/api/method/kesari_jefs.api.download_generated_artifact?token=${encodeURIComponent(res.zip_token)}">Download Increment Letters ZIP</a>`);
        }
      } catch (e) { showErr(e); }
    });
    root.find('#wr-watch').on('click', async () => { try { await api('run_watcher_check', {}, true); renderWageRevision(root); } catch (e) { showErr(e); } });
  }

  async function renderDocumentsRegister(root, q = '') {
    const docs = await api('list_documents', { q });
    const rows = docs.map((d) => `
      <tr>
        <td class="jefs-mono"><b>${esc(d.ref_no)}</b></td>
        <td>${esc(d.doc_type)}</td>
        <td>${esc(d.employee_code)} · ${esc(d.employee_name)}</td>
        <td>v${d.version}</td>
        <td>${esc(d.generated_by)}<br/><span class="jefs-muted">${esc(String(d.generated_at).slice(0, 16))}</span></td>
        <td>${d.downloaded_count}</td>
        <td>${d.is_void ? `<span class="jefs-pill jefs-err" title="${esc(d.void_reason)}">VOID</span>` : '<span class="jefs-pill jefs-ok">Valid</span>'}</td>
        <td>
          <a class="btn btn-xs btn-default" href="/api/method/kesari_jefs.api.download_document?doc_id=${encodeURIComponent(d.name)}&fmt=pdf">PDF</a>
          <a class="btn btn-xs btn-default" href="/api/method/kesari_jefs.api.download_document?doc_id=${encodeURIComponent(d.name)}&fmt=docx">DOCX</a>
          ${!d.is_void ? `<button class="btn btn-xs btn-danger dr-void" data-id="${esc(d.name)}">Void</button>` : ''}
        </td>
      </tr>`).join('');

    root.html(`
      <div class="jefs-desk-wrap">
        <div class="jefs-card">
          <div class="jefs-form-row">
            <div><input type="text" class="form-control" id="dr-q" value="${esc(q)}" placeholder="Search Ref No, Employee Code, Name, Type..." /></div>
            <div><button class="btn btn-primary" id="dr-search">Search</button></div>
          </div>
          <div class="jefs-table-wrap"><table class="jefs-table"><thead><tr><th>Ref No</th><th>Type</th><th>Employee</th><th>Ver</th><th>Generated</th><th>DL</th><th>Status</th><th>Actions</th></tr></thead><tbody>${rows || '<tr><td colspan="8" class="jefs-muted">No documents generated yet.</td></tr>'}</tbody></table></div>
        </div>
      </div>`);

    root.find('#dr-search').on('click', () => renderDocumentsRegister(root, root.find('#dr-q').val()));
    root.find('.dr-void').on('click', function () {
      const id = this.dataset.id;
      frappe.prompt([{ fieldname: 'reason', label: 'Void Reason', fieldtype: 'Data', reqd: 1 }], async (vals) => {
        try { await api('void_document', { doc_id: id, reason: vals.reason }, true); renderDocumentsRegister(root, root.find('#dr-q').val()); } catch (e) { showErr(e); }
      }, __('Void Document'));
    });
  }

  async function renderEmployees(root, q = '') {
    const emps = await api('list_employees', { q });
    const rows = emps.map((e) => `
      <tr>
        <td><b>${esc(e.employee_code)}</b></td>
        <td>${esc(e.full_name)}</td>
        <td>${esc(e.designation)}</td>
        <td>${esc(e.client_site)}</td>
        <td>${esc(e.date_of_joining)}</td>
        <td class="jefs-mono">${esc(e.aadhaar_masked || '-')}</td>
        <td><span class="jefs-pill ${e.kit_ready ? 'jefs-ok' : 'jefs-warn'}">${e.kit_ready ? 'Kit Ready' : 'Missing'}</span></td>
        <td><span class="jefs-pill ${e.status === 'ACTIVE' ? 'jefs-ok' : 'jefs-neutral'}">${esc(e.status)}</span></td>
        <td>
          <button class="btn btn-xs btn-default emp-view" data-code="${esc(e.employee_code)}">View / PII / Nominees</button>
          ${e.frappe_employee ? `<button class="btn btn-xs btn-default" onclick="frappe.set_route('Form', 'Employee', '${esc(e.frappe_employee)}')">HR Record</button>` : ''}
          ${e.status === 'ACTIVE' ? `<button class="btn btn-xs btn-danger emp-exit" data-code="${esc(e.employee_code)}">Exit</button>` : ''}
        </td>
      </tr>`).join('');

    root.html(`
      <div class="jefs-desk-wrap">
        <div class="jefs-card">
          <div class="jefs-form-row">
            <div><input type="text" class="form-control" id="emp-q" value="${esc(q)}" placeholder="Search Code, Name, Site..." /></div>
            <div><button class="btn btn-primary" id="emp-search">Filter</button></div>
          </div>
          <div class="jefs-table-wrap"><table class="jefs-table"><thead><tr><th>Code</th><th>Name</th><th>Designation</th><th>Site</th><th>DOJ</th><th>Aadhaar</th><th>Kit</th><th>Status</th><th>Actions</th></tr></thead><tbody>${rows}</tbody></table></div>
        </div>
      </div>`);

    root.find('#emp-search').on('click', () => renderEmployees(root, root.find('#emp-q').val()));
    root.find('.emp-view').on('click', async function () {
      const code = this.dataset.code;
      const d = await api('get_employee_detail', { employee_code: code });
      const e = d.employee;
      const dlg = new frappe.ui.Dialog({
        title: `${e.full_name} (${e.employee_code})`,
        size: 'large',
        fields: [{ fieldtype: 'HTML', fieldname: 'body' }],
      });
      const nomRows = d.nominees.map((n) => `<tr><td><select class="form-control n-p"><option ${n.purpose==='GRATUITY'?'selected':''}>GRATUITY</option><option ${n.purpose==='PF'?'selected':''}>PF</option><option ${n.purpose==='EPS'?'selected':''}>EPS</option></select></td><td><input class="form-control n-n" value="${esc(n.nominee_name)}"/></td><td><input class="form-control n-r" value="${esc(n.relationship)}"/></td><td><input type="number" class="form-control n-s" value="${esc(n.share_pct)}"/></td></tr>`).join('');
      dlg.fields_dict.body.$wrapper.html(`
        <div class="jefs-form-row">
          <div><b>Site:</b> ${esc(e.client_site)}</div>
          <div><b>Mobile:</b> ${esc(e.mobile)}</div>
          <div><b>Aadhaar:</b> <span class="jefs-mono" id="d-aad">${esc(e.aadhaar_masked || '-')}</span></div>
          <div><b>PAN:</b> <span class="jefs-mono" id="d-pan">${esc(e.pan_masked || '-')}</span></div>
        </div>
        <button class="btn btn-xs btn-default" id="d-reveal">Reveal Full PII (Audited)</button>
        <hr/>
        <h4>Nominees (Sum per purpose = 100%)</h4>
        <table class="jefs-table"><thead><tr><th>Purpose</th><th>Name</th><th>Relation</th><th>Share %</th></tr></thead><tbody id="d-nom">${nomRows}</tbody></table>
        <div style="margin-top:8px;display:flex;gap:8px;">
          <button class="btn btn-xs btn-default" id="d-add-nom">+ Add Nominee</button>
          <button class="btn btn-xs btn-primary" id="d-save-nom">Save Nominees</button>
        </div>
      `);
      dlg.fields_dict.body.$wrapper.find('#d-reveal').on('click', async () => {
        try {
          const r = await api('reveal_employee_pii', { employee_code: code }, true);
          dlg.fields_dict.body.$wrapper.find('#d-aad').text(r.aadhaar || '-');
          dlg.fields_dict.body.$wrapper.find('#d-pan').text(r.pan || '-');
          frappe.show_alert({ message: 'PII reveal audited', indicator: 'orange' });
        } catch (err) { showErr(err); }
      });
      dlg.fields_dict.body.$wrapper.find('#d-add-nom').on('click', () => {
        dlg.fields_dict.body.$wrapper.find('#d-nom').append('<tr><td><select class="form-control n-p"><option>GRATUITY</option><option>PF</option><option>EPS</option></select></td><td><input class="form-control n-n"/></td><td><input class="form-control n-r"/></td><td><input type="number" class="form-control n-s" value="100"/></td></tr>');
      });
      dlg.fields_dict.body.$wrapper.find('#d-save-nom').on('click', async () => {
        const items = [];
        dlg.fields_dict.body.$wrapper.find('#d-nom tr').each((_, tr) => {
          const name = $(tr).find('.n-n').val().trim();
          if (!name) return;
          items.push({ purpose: $(tr).find('.n-p').val(), nominee_name: name, relationship: $(tr).find('.n-r').val(), share_pct: Number($(tr).find('.n-s').val() || 0) });
        });
        try { await api('save_nominees', { employee_code: code, nominees_json: JSON.stringify(items) }, true); dlg.hide(); renderEmployees(root, q); } catch (err) { showErr(err); }
      });
      dlg.show();
    });
    root.find('.emp-exit').on('click', function () {
      const code = this.dataset.code;
      frappe.prompt([
        { fieldname: 'exit_date', label: 'Exit Date', fieldtype: 'Date', default: frappe.datetime.get_today(), reqd: 1 },
        { fieldname: 'exit_reason', label: 'Reason', fieldtype: 'Select', options: 'RESIGNATION\nRETIREMENT\nEND_OF_CONTRACT\nTERMINATION\nABSCONDING\nDEATH', default: 'RESIGNATION', reqd: 1 },
        { fieldname: 'conduct', label: 'Conduct', fieldtype: 'Data', default: 'Good' },
      ], async (vals) => {
        try {
          deskState.activeFnf = await api('record_employee_exit', { employee_code: code, exit_date: vals.exit_date, last_working_day: vals.exit_date, exit_reason: vals.exit_reason, conduct: vals.conduct }, true);
          frappe.set_route('jefs-fnf');
        } catch (e) { showErr(e); }
      }, __('Record Exit & Initiate F&F'));
    });
  }

  async function renderReports(root) {
    const items = [
      ['joiners', 'Joiners Register'],
      ['exits', 'Exits Register'],
      ['documents-generated', 'Documents Generated'],
      ['fnf-register', 'F&F Register'],
      ['pending-fnf', 'Pending F&F (2-Working-Day Deadline)'],
      ['missing-data', 'Missing Data / Blocked Kits'],
      ['wage-revision', 'Wage Revisions'],
    ];
    root.html(`
      <div class="jefs-desk-wrap">
        <div class="jefs-grid-4">
          ${items.map(([k, title]) => `<div class="jefs-card"><h4>${title}</h4><a class="btn btn-sm btn-primary" href="/api/method/kesari_jefs.api.download_report?report_type=${k}">Download .xlsx</a></div>`).join('')}
          <div class="jefs-card"><h4>Client F&amp;F Workbook</h4><a class="btn btn-sm btn-primary" href="/api/method/kesari_jefs.api.export_fnf_excel">Download .xlsx</a></div>
        </div>
      </div>`);
  }

  async function renderSettings(root) {
    const data = await api('get_settings_data');
    const tab = deskState.settingsTab;
    const tabsHtml = ['company', 'templates', 'statutory', 'sites', 'users', 'audit'].map((t) => `<button class="jefs-tab ${tab === t ? 'active' : ''}" data-t="${t}">${t.toUpperCase()}</button>`).join('');

    let body = '';
    if (tab === 'company') {
      const c = data.company;
      body = `
        <div class="jefs-card">
          <div class="jefs-form-row">
            <div><label>Legal Name</label><input class="form-control" id="co-n" value="${esc(c.legal_name)}" /></div>
            <div><label>Ref Prefix</label><input class="form-control" id="co-p" value="${esc(c.ref_prefix)}" /></div>
            <div><label>Signatory Name</label><input class="form-control" id="co-s" value="${esc(c.signatory_name)}" /></div>
            <div><label>Designation</label><input class="form-control" id="co-d" value="${esc(c.signatory_designation)}" /></div>
            <div><label>Phone</label><input class="form-control" id="co-ph" value="${esc(c.phone)}" /></div>
            <div><label>Email</label><input class="form-control" id="co-em" value="${esc(c.email)}" /></div>
          </div>
          <label>Address</label><textarea class="form-control" id="co-a" rows="2">${esc(c.address)}</textarea>
          <button class="btn btn-primary" id="co-save" style="margin-top:10px;">Save Company Profile</button>
        </div>`;
    } else if (tab === 'templates') {
      const tRows = data.templates.map((t) => `
        <tr>
          <td><b>${esc(t.doc_type)}</b></td><td>${esc(t.template_name)}</td><td>v${t.version} (${t.engine})</td>
          <td>${t.is_active ? '<span class="jefs-pill jefs-ok">Active</span>' : `<button class="btn btn-xs btn-default t-act" data-id="${esc(t.name)}">Activate</button>`}</td>
          <td><button class="btn btn-xs btn-default t-prev" data-id="${esc(t.name)}">Preview PDF</button></td>
        </tr>`).join('');
      body = `
        <div class="jefs-card">
          <h3>Editable .docx Templates</h3>
          <div class="jefs-form-row">
            <div><label>Doc Type</label><select class="form-control" id="tp-type"><option>OFFER_LETTER</option><option>APPOINTMENT_LETTER</option><option>GRATUITY_FORM_F</option><option>EPFO_FORM_2</option><option>POLICE_VERIFICATION</option><option>INCREMENT_LETTER</option><option>SERVICE_CERTIFICATE</option></select></div>
            <div><label>Template Name</label><input class="form-control" id="tp-name" value="Custom Client Format" /></div>
            <div><label>.docx File</label><input type="file" class="form-control" id="tp-file" accept=".docx" /></div>
            <div style="display:flex;align-items:flex-end;"><button class="btn btn-primary" id="tp-up">Upload &amp; Validate</button></div>
          </div>
          <div class="jefs-table-wrap"><table class="jefs-table"><thead><tr><th>Type</th><th>Name</th><th>Ver</th><th>Active</th><th>Preview</th></tr></thead><tbody>${tRows}</tbody></table></div>
        </div>`;
    } else if (tab === 'statutory') {
      const sRows = data.statutory.map((s) => `<tr><td class="jefs-mono">${esc(s.setting_key)}</td><td><b>${esc(s.setting_value)}</b></td><td>${esc(s.effective_from)}</td><td class="jefs-muted">${esc(s.note)}</td></tr>`).join('');
      body = `<div class="jefs-card"><h3>Effective-Dated Statutory Settings</h3><div class="jefs-table-wrap"><table class="jefs-table"><thead><tr><th>Key</th><th>Value</th><th>Effective From</th><th>Source</th></tr></thead><tbody>${sRows}</tbody></table></div></div>`;
    } else if (tab === 'sites') {
      const srRows = data.site_rules.map((r) => `<tr><td><b>${esc(r.site_code)}</b></td><td>${esc(r.site_name)}</td><td>${r.include_bonus?'Yes':'No'}</td><td>${r.include_leave?'Yes':'No'}</td><td>${r.include_gratuity?'Yes':'No'}</td><td class="jefs-muted">${esc(r.notes)}</td></tr>`).join('');
      body = `<div class="jefs-card"><h3>Client Site Rules (CONMAT / EXECHON / SAT)</h3><div class="jefs-table-wrap"><table class="jefs-table"><thead><tr><th>Code</th><th>Principal Employer</th><th>Bonus</th><th>Leave</th><th>Gratuity</th><th>Notes</th></tr></thead><tbody>${srRows}</tbody></table></div></div>`;
    } else if (tab === 'users') {
      body = `<div class="jefs-card"><h3>Maker-Checker Role Accounts</h3><p class="jefs-muted">Approver login for F&amp;F / Wage Revisions: <b>approver@kesari.local</b> (password: <code>Kesari@2026</code>). Also seeded: <code>onboarding@kesari.local</code>, <code>payroll@kesari.local</code>, <code>exitdesk@kesari.local</code>, <code>auditor@kesari.local</code>.</p></div>`;
    } else {
      const logs = await api('list_audit_logs', { limit: 100 });
      const lRows = logs.map((l) => `<tr><td class="jefs-mono">${esc(String(l.logged_at).slice(0, 19))}</td><td>${esc(l.user_id)}</td><td><b>${esc(l.action)}</b></td><td>${esc(l.entity)}</td><td class="jefs-mono">${esc(l.entity_id)}</td></tr>`).join('');
      body = `<div class="jefs-card"><h3>Append-Only Audit Log</h3><div class="jefs-table-wrap"><table class="jefs-table"><thead><tr><th>Time</th><th>User</th><th>Action</th><th>Entity</th><th>ID</th></tr></thead><tbody>${lRows}</tbody></table></div></div>`;
    }

    root.html(`<div class="jefs-desk-wrap"><div class="jefs-tabs">${tabsHtml}</div>${body}</div>`);
    root.find('.jefs-tab').on('click', function () { deskState.settingsTab = this.dataset.t; renderSettings(root); });
    root.find('#co-save').on('click', async () => {
      try {
        await api('save_company_profile', { data_json: JSON.stringify({ legal_name: root.find('#co-n').val(), ref_prefix: root.find('#co-p').val(), signatory_name: root.find('#co-s').val(), signatory_designation: root.find('#co-d').val(), phone: root.find('#co-ph').val(), email: root.find('#co-em').val(), address: root.find('#co-a').val() }) }, true);
        frappe.show_alert({ message: 'Company saved', indicator: 'green' });
      } catch (e) { showErr(e); }
    });
    root.find('#tp-up').on('click', async () => {
      const f = root.find('#tp-file')[0].files[0];
      if (!f) return frappe.msgprint('Choose a .docx file');
      const fd = new FormData();
      fd.append('doc_type', root.find('#tp-type').val());
      fd.append('template_name', root.find('#tp-name').val());
      fd.append('file', f);
      try { await apiUpload('upload_docx_template', fd); renderSettings(root); } catch (e) { showErr(e); }
    });
    root.find('.t-act').on('click', async function () { await api('activate_template', { template_id: this.dataset.id }, true); renderSettings(root); });
    root.find('.t-prev').on('click', function () {
      const tid = this.dataset.id;
      frappe.prompt([{ fieldname: 'code', label: 'Employee Code (e.g. KM1023)', fieldtype: 'Data', default: 'KM1023', reqd: 1 }], async (v) => {
        try {
          const r = await api('preview_template', { template_id: tid, employee_code: v.code }, true);
          window.open(`/api/method/kesari_jefs.api.download_generated_artifact?token=${encodeURIComponent(r.file_token)}`, '_blank');
        } catch (e) { showErr(e); }
      }, __('Preview Template'));
    });
  }

  const FF_LOGO = '/assets/kesari_jefs/images/ff-logo.svg';
  const ATTENDANCE_KEEP = new Set([
    'Home',
    'Dashboard',
    'Attendance',
    'Employee Checkin',
    'Employee Attendance Tool',
    'Attendance Request',
    'Reports',
    'Monthly Attendance Sheet',
    'Settings',
  ]);

  function openFFAboutDialog() {
    if (frappe.ui.misc.ff_about_dialog) {
      frappe.ui.misc.ff_about_dialog.show();
      return;
    }
    const dialog = new frappe.ui.Dialog({ title: __('About F&F') });
    $(dialog.wrapper).addClass('about-dialog');
    $(dialog.body).html(`
      <div class="about-body flex flex-col gap-5 items-start">
        <div class="flex flex-col items-center gap-3 py-3 w-full">
          <img src="${FF_LOGO}" alt="F&amp;F" style="width:56px;height:56px;border-radius:14px;" />
          <div style="font-size:20px;font-weight:700;color:#0f172a;">F&amp;F</div>
          <p class="text-p-sm text-ink-gray-5 m-0">Employee Joining &amp; Exit Formality Software</p>
        </div>
        <div class="about-info-rows flex flex-col gap-3 w-full">
          <div class="about-info-row flex items-center justify-between">
            <div class="about-info-content flex flex-col gap-1">
              <div class="about-info-title text-base-semibold text-ink-gray-8">Application</div>
              <div class="about-info-sub text-p-sm text-ink-gray-5">F&amp;F · Kesari Manpower Solutions</div>
            </div>
          </div>
          <div class="about-info-row flex items-center justify-between">
            <div class="about-info-content flex flex-col gap-1">
              <div class="about-info-title text-base-semibold text-ink-gray-8">Version</div>
              <div class="about-info-sub text-p-sm text-ink-gray-5">1.0.0</div>
            </div>
          </div>
        </div>
      </div>
    `);
    $(dialog.footer)
      .removeClass('hide')
      .prepend('<div class="about-footer text-p-sm text-ink-gray-4 text-center">Kesari Manpower Solutions · Vadodara</div>');
    frappe.ui.misc.ff_about_dialog = dialog;
    dialog.show();
  }

  function cleanMenuOptions(options) {
    if (!Array.isArray(options)) return options;
    const out = [];
    for (const opt of options) {
      if (!opt || typeof opt !== 'object') continue;
      const lbl = String(opt.label || '');
      const href = String(opt.href || opt.url || '');
      if (
        /frappe|support/i.test(lbl) ||
        /frappe\.(io|cloud)|discuss\.frappe|support\.frappe|docs\.erpnext|frappehr\.com|youtube\.com|youtu\.be/i.test(href)
      ) {
        continue;
      }
      const nextOpt = { ...opt };
      if (/shift\s*&\s*attendance/i.test(lbl)) {
        nextOpt.label = lbl.replace(/shift\s*&\s*attendance/gi, 'Attendance');
      }
      if (Array.isArray(nextOpt.submenu)) {
        nextOpt.submenu = cleanMenuOptions(nextOpt.submenu);
        if (!nextOpt.submenu.some((s) => !s.options || s.options.length > 0)) continue;
      }
      if (Array.isArray(nextOpt.options)) {
        nextOpt.options = cleanMenuOptions(nextOpt.options);
        if (!nextOpt.options.length) continue;
      }
      out.push(nextOpt);
    }
    return out;
  }

  function cleanVisibleFFDom() {
    try {
      document.querySelectorAll('button.dock-item[aria-label="Flow"], .sidebar-flow, .flow-launcher').forEach((el) => el.remove());
      document.querySelectorAll('.dock-item use[href="#icon-flow"], button use[href="#icon-flow"]').forEach((u) => {
        const btn = u.closest('.dock-item, button');
        if (btn) btn.remove();
      });
      document.querySelectorAll('a[href*="youtube.com"], a[href*="youtu.be"], a[href*="frappe.io"], a[href*="support.frappe.io"], a[href*="frappecloud.com"], a[href*="docs.erpnext.com"], a[href*="frappehr.com"], .help-video-link, [data-youtubeid]').forEach((el) => {
        const card = el.closest('.dropdown-item, [role="menuitem"], .onboarding-step-footer .btn, .help-links');
        el.style.display = 'none';
        if (card) card.style.display = 'none';
      });
      document.querySelectorAll('.sidebar-header-title, .title-text, .page-head .title-area h3, .dock-item').forEach((el) => {
        if (el.childElementCount === 0 && /shift\s*&\s*attendance/i.test(el.textContent || '')) {
          el.textContent = el.textContent.replace(/shift\s*&\s*attendance/gi, 'Attendance');
        }
        const aria = el.getAttribute && el.getAttribute('aria-label');
        if (aria && /shift\s*&\s*attendance/i.test(aria)) {
          el.setAttribute('aria-label', aria.replace(/shift\s*&\s*attendance/gi, 'Attendance'));
        }
      });
      document.querySelectorAll('.dropdown-item, .dropdown-menu-item, .es-menu__item, [role="menuitem"], .es-menu-item, .menu-row, .es-popover-item').forEach((el) => {
        if (/frappe\s*support/i.test(el.textContent || '')) el.remove();
      });
    } catch (_) {}
  }

  function applyFFBranding() {
    try {
      if (window.frappe && frappe.boot) {
        if (Array.isArray(frappe.boot.app_data)) {
          frappe.boot.app_data = frappe.boot.app_data.filter((app) => app.app_name === 'hrms' || app.app_name === 'kesari_jefs');
          frappe.boot.app_data.forEach((app) => {
            if (app.app_name === 'hrms') {
              app.app_title = 'F&F';
              app.app_logo_url = FF_LOGO;
              app.app_route = '/desk/kesari-jefs/jefs-dashboard';
              app.on_apps_screen = true;
              app.sequence_id = 1;
            } else {
              app.app_title = 'F&F';
              app.app_logo_url = FF_LOGO;
              app.on_apps_screen = false;
            }
          });
        }
        if (frappe.boot.dock && typeof frappe.boot.dock === 'object') {
          delete frappe.boot.dock.erpnext;
          delete frappe.boot.dock.frappe;
        }
        if (frappe.boot.module_sidebars && typeof frappe.boot.module_sidebars === 'object') {
          Object.keys(frappe.boot.module_sidebars).forEach((k) => {
            const sb = frappe.boot.module_sidebars[k];
            if ((sb && sb.app === 'erpnext') || k === 'Flow' || k === 'Studio' || k === 'Build') {
              delete frappe.boot.module_sidebars[k];
            }
          });
        }
        frappe.boot.home_shell = 'Kesari JEFS';
        frappe.boot.home_page = 'jefs-dashboard';
        frappe.boot.studio_apps = [];
        frappe.boot.flow_enabled = false;
        frappe.boot.app_logo_url = FF_LOGO;
        if (frappe.boot.navbar_settings) {
          frappe.boot.navbar_settings.app_logo = FF_LOGO;
          ['help_dropdown', 'settings_dropdown'].forEach((k) => {
            if (Array.isArray(frappe.boot.navbar_settings[k])) {
              frappe.boot.navbar_settings[k] = frappe.boot.navbar_settings[k].filter(
                (r) => !/frappe|erpnext/i.test(`${r.item_label || ''} ${r.route || ''}`)
              );
            }
          });
        }
        if (frappe.boot.sysdefaults) {
          frappe.boot.sysdefaults.app_name = 'F&F';
        }
        const dockHrms = frappe.boot.dock && frappe.boot.dock.hrms;
        if (Array.isArray(dockHrms)) {
          dockHrms.forEach((r) => {
            if (r && (r.link_to === 'Shift & Attendance' || r.link_to === 'Attendance')) r.title = 'Attendance';
          });
        }
        ['Shift & Attendance', 'Attendance'].forEach((k) => {
          const sa = frappe.boot.module_sidebars && frappe.boot.module_sidebars[k];
          if (sa && typeof sa === 'object') {
            sa.label = 'Attendance';
            if (Array.isArray(sa.items)) {
              sa.items = sa.items.filter((it) => ATTENDANCE_KEEP.has(it.label));
            }
          }
        });
      }
      if (window.frappe && typeof frappe.provide === 'function') {
        frappe.provide('frappe.flow');
        frappe.flow.is_enabled = () => false;
        frappe.flow.can_offer = () => false;
        frappe.provide('frappe.help');
        frappe.help.youtube_id = {};
        frappe.help.help_links = {};
        frappe.help.has_video = () => false;
        frappe.help.show_video = () => {};
        frappe.provide('frappe.ui.misc');
        frappe.ui.misc.about = openFFAboutDialog;
        frappe.provide('frappe.ui.toolbar');
        frappe.ui.toolbar.show_about = openFFAboutDialog;
      }
      document.querySelectorAll('link[rel="icon"], link[rel="shortcut icon"]').forEach((el) => {
        if (el.getAttribute('href') !== FF_LOGO) el.setAttribute('href', FF_LOGO);
      });
      if (document.title) {
        document.title = document.title
          .replace(/Frappe HR/gi, 'F&F')
          .replace(/Frappe/gi, 'F&F')
          .replace(/Shift\s*&\s*Attendance/gi, 'Attendance');
      }
      cleanVisibleFFDom();
    } catch (_) {}
  }

  function redirectDesktopToJEFS() {
    try {
      if (!window.frappe || typeof frappe.get_route_str !== 'function' || typeof frappe.set_route !== 'function') return;
      const r = frappe.get_route_str();
      if (r === '' || r === 'desktop' || r === 'jefs-dashboard' || r === 'home') {
        frappe.set_route('kesari-jefs', 'jefs-dashboard');
      }
    } catch (_) {}
  }

  function installFFBrandingHooks() {
    applyFFBranding();
    redirectDesktopToJEFS();
    if (window.frappe && frappe.ui && typeof frappe.ui.Dropdown === 'function' && !frappe.ui.Dropdown.__ff_patched) {
      const OrigDropdown = frappe.ui.Dropdown;
      const origOpen = OrigDropdown.prototype.open;
      if (typeof origOpen === 'function') {
        OrigDropdown.prototype.open = function (...openArgs) {
          if (Array.isArray(this.options)) {
            this.options = cleanMenuOptions(this.options);
          } else if (typeof this.options === 'function') {
            const origFn = this.options;
            this.options = (...fnArgs) => {
              const res = origFn(...fnArgs);
              return res && typeof res.then === 'function' ? res.then(cleanMenuOptions) : cleanMenuOptions(res);
            };
          }
          return origOpen.apply(this, openArgs);
        };
      }
      const WrappedDropdown = function (opts) {
        if (opts) {
          if (Array.isArray(opts.options)) {
            opts = { ...opts, options: cleanMenuOptions(opts.options) };
          } else if (typeof opts.options === 'function') {
            const origFn = opts.options;
            opts = {
              ...opts,
              options: (...fnArgs) => {
                const res = origFn(...fnArgs);
                return res && typeof res.then === 'function' ? res.then(cleanMenuOptions) : cleanMenuOptions(res);
              },
            };
          }
        }
        return new OrigDropdown(opts);
      };
      WrappedDropdown.prototype = OrigDropdown.prototype;
      Object.setPrototypeOf(WrappedDropdown, OrigDropdown);
      WrappedDropdown.__ff_patched = true;
      frappe.ui.Dropdown = WrappedDropdown;
    }
    if (window.frappe && frappe.utils && !frappe.utils.__ff_patched) {
      frappe.utils.__ff_patched = true;
      const origGetApps = frappe.utils.get_apps_screen_apps;
      if (typeof origGetApps === 'function') {
        frappe.utils.get_apps_screen_apps = function (...args) {
          applyFFBranding();
          return origGetApps.apply(this, args);
        };
      }
      const origAppLogo = frappe.utils.app_logo;
      if (typeof origAppLogo === 'function') {
        frappe.utils.app_logo = function (app, ...args) {
          applyFFBranding();
          if (app && app.app_name === 'hrms') {
            app = { ...app, app_title: 'F&F', app_logo_url: FF_LOGO };
          }
          return origAppLogo.call(this, app, ...args);
        };
      }
    }
    if (window.frappe && frappe.router && !frappe.router.__ff_route_hooked && typeof frappe.router.on === 'function') {
      frappe.router.__ff_route_hooked = true;
      frappe.router.on('change', () => {
        setTimeout(applyFFBranding, 0);
        setTimeout(redirectDesktopToJEFS, 0);
        setTimeout(cleanVisibleFFDom, 150);
      });
    }
    if (!window.__ff_observer && document.body) {
      window.__ff_observer = new MutationObserver(() => cleanVisibleFFDom());
      window.__ff_observer.observe(document.body, { childList: true, subtree: true });
    }
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', installFFBrandingHooks);
  } else {
    installFFBrandingHooks();
  }
  setTimeout(installFFBrandingHooks, 0);

  window.KesariDesk = {
    mount(wrapper, title, mode, arg) {
      installFFBrandingHooks();
      const page = frappe.ui.make_app_page({ parent: wrapper, title: __(title), single_column: true });
      const $main = $(page.main);
      const run = () => {
        if (mode === 'dashboard') renderDashboard($main);
        else if (mode === 'upload') renderUploadFeed($main, arg);
        else if (mode === 'joining-kit') renderJoiningKit($main);
        else if (mode === 'fnf') renderFnF($main);
        else if (mode === 'service-certificates') renderServiceCertificates($main);
        else if (mode === 'wage-revision') renderWageRevision($main);
        else if (mode === 'documents-register') renderDocumentsRegister($main);
        else if (mode === 'employees') renderEmployees($main);
        else if (mode === 'reports') renderReports($main);
        else if (mode === 'settings') renderSettings($main);
      };
      wrapper._jefs_refresh = run;
      run();
    },
  };
})();
