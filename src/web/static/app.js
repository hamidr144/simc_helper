document.addEventListener('DOMContentLoaded', () => {
    // State
    let parsedData = null;

    // Elements
    const tabs = document.querySelectorAll('.tab-btn');
    const tabContents = document.querySelectorAll('.tab-content');
    
    // Modals & Terminals
    const modal = document.getElementById('modal');
    const modalClose = document.querySelector('.close');
    const modalConsole = document.getElementById('modal-console');
    const simConsole = document.getElementById('sim-console');

    // Buttons
    const btnUpdateSimc = document.getElementById('btn-update-simc');
    const btnUpdateSimcMain = document.getElementById('btn-update-simc-main');
    const btnParseAddon = document.getElementById('btn-parse-addon');
    const btnGenerateSim = document.getElementById('btn-generate-sim');
    const btnRunSim = document.getElementById('btn-run-sim');
    const btnSaveConfig = document.getElementById('btn-save-config');

    // Config loading
    const configSlots = {
        enchantments: ["head", "neck", "shoulder", "back", "chest", "wrist", "hands", "waist", "legs", "feet", "finger", "main_hand", "off_hand"],
        gems: ["head", "neck", "shoulder", "back", "chest", "wrist", "hands", "waist", "legs", "feet", "finger", "trinket"]
    };

    function renderConfigForm(config) {
        ['enchantments', 'gems'].forEach(category => {
            const container = document.getElementById(`config-${category}`);
            container.innerHTML = '';
            configSlots[category].forEach(slot => {
                const label = document.createElement('label');
                label.textContent = slot.replace('_', ' ').toUpperCase();
                const input = document.createElement('input');
                input.type = 'text';
                input.name = `${category}-${slot}`;
                input.placeholder = "e.g., 1234, 5678";
                const values = config[category] && config[category][slot] ? config[category][slot] : [];
                input.value = values.join(', ');
                label.appendChild(input);
                container.appendChild(label);
            });
        });
    }

    fetch('/api/config')
        .then(res => res.json())
        .then(data => renderConfigForm(data))
        .catch(err => console.error("Error loading config:", err));

    if (btnSaveConfig) {
        btnSaveConfig.addEventListener('click', async () => {
            const newConfig = { enchantments: {}, gems: {} };
            ['enchantments', 'gems'].forEach(category => {
                configSlots[category].forEach(slot => {
                    const input = document.querySelector(`input[name="${category}-${slot}"]`);
                    if (input) {
                        const val = input.value.trim();
                        newConfig[category][slot] = val ? val.split(',').map(s => parseInt(s.trim(), 10)).filter(n => !isNaN(n)) : [];
                    }
                });
            });

            btnSaveConfig.disabled = true;
            try {
                const res = await fetch('/api/config', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(newConfig)
                });
                if (res.ok) {
                    const status = document.getElementById('config-save-status');
                    status.textContent = "Saved successfully!";
                    setTimeout(() => status.textContent = "", 3000);
                }
            } catch (err) {
                alert("Error saving configuration.");
            } finally {
                btnSaveConfig.disabled = false;
            }
        });
    }

    // Tab Management
    function switchTab(targetId) {
        tabs.forEach(t => t.classList.remove('active'));
        tabContents.forEach(tc => tc.classList.remove('active'));
        
        const tabBtn = document.querySelector(`.tab-btn[data-target="${targetId}"]`);
        if (tabBtn && !tabBtn.disabled) {
            tabBtn.classList.add('active');
            document.getElementById(targetId).classList.add('active');
        }
    }

    tabs.forEach(tab => {
        tab.addEventListener('click', () => {
            if (!tab.disabled) switchTab(tab.dataset.target);
        });
    });

    // Update / Build SimC
    function triggerSimcUpdate() {
        modal.style.display = "block";
        modalConsole.innerHTML = "Starting SimC check & build...\n";
        
        const source = new EventSource('/api/update-simc');
        source.onmessage = function(event) {
            const data = JSON.parse(event.data);
            if (data.type === 'log') {
                modalConsole.innerHTML += data.text + '\n';
                modalConsole.scrollTop = modalConsole.scrollHeight;
            } else if (data.type === 'exit') {
                source.close();
                if (data.code === 0) {
                    modalConsole.innerHTML += "\nSUCCESS: SimulationCraft updated and built.";
                    document.getElementById('simc-status').textContent = "Ready";
                    document.getElementById('simc-status').style.color = "var(--accent-color)";
                } else {
                    modalConsole.innerHTML += `\nERROR: Process exited with code ${data.code}`;
                    document.getElementById('simc-status').textContent = "Error";
                    document.getElementById('simc-status').style.color = "red";
                }
            }
        };
    }

    btnUpdateSimc.addEventListener('click', triggerSimcUpdate);
    if (btnUpdateSimcMain) btnUpdateSimcMain.addEventListener('click', triggerSimcUpdate);

    modalClose.onclick = () => { modal.style.display = "none"; };
    window.onclick = (e) => { if (e.target == modal) modal.style.display = "none"; };

    // Parse Addon
    btnParseAddon.addEventListener('click', async () => {
        const text = document.getElementById('addon-input').value;
        if (!text.trim()) return alert("Please paste addon text first.");

        btnParseAddon.disabled = true;
        btnParseAddon.textContent = "Parsing...";

        try {
            const res = await fetch('/api/parse-addon', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ addon_text: text })
            });

            parsedData = await res.json();
            
            document.getElementById('character-info').innerHTML = `
                <h3>Character: ${parsedData.char_name} (${parsedData.char_class})</h3>
            `;

            renderGearSelection(parsedData.items_by_slot, parsedData.item_names, parsedData.equipped_gear);
            
            document.getElementById('btn-tab-gear').disabled = false;
            switchTab('tab-gear');
        } catch (e) {
            alert("Error parsing addon data.");
            console.error(e);
        } finally {
            btnParseAddon.disabled = false;
            btnParseAddon.textContent = "Parse Addon Data";
        }
    });

    function renderGearSelection(itemsBySlot, itemNames, equippedGear) {
        const container = document.getElementById('gear-form');
        container.innerHTML = '';

        for (const [slot, items] of Object.entries(itemsBySlot)) {
            const card = document.createElement('div');
            card.className = 'slot-card';
            
            const title = document.createElement('h3');
            title.textContent = slot.toUpperCase();
            card.appendChild(title);

            const equippedInSlot = slot === "finger" ? [equippedGear.finger1, equippedGear.finger2] : 
                                   slot === "trinket" ? [equippedGear.trinket1, equippedGear.trinket2] : 
                                   [equippedGear[slot]];

            items.forEach(item => {
                const label = document.createElement('label');
                label.className = 'item-checkbox';
                
                const cb = document.createElement('input');
                cb.type = 'checkbox';
                cb.name = slot;
                cb.value = item;
                
                // Pre-check equipped items
                if (equippedInSlot.includes(item)) cb.checked = true;

                const txt = document.createTextNode(itemNames[item] || item);
                
                label.appendChild(cb);
                label.appendChild(txt);
                
                if (equippedInSlot.includes(item)) {
                    const badge = document.createElement('strong');
                    badge.textContent = ' [E]';
                    badge.style.color = 'var(--accent-color)';
                    label.appendChild(badge);
                }

                card.appendChild(label);
            });

            container.appendChild(card);
        }
    }

    // Generate Combinations
    btnGenerateSim.addEventListener('click', async () => {
        if (!parsedData) return;

        btnGenerateSim.disabled = true;
        btnGenerateSim.textContent = "Generating...";

        // Collect selected items
        const selectedItems = {};
        const checkboxes = document.querySelectorAll('#gear-form input[type="checkbox"]:checked');
        checkboxes.forEach(cb => {
            if (!selectedItems[cb.name]) selectedItems[cb.name] = [];
            selectedItems[cb.name].push(cb.value);
        });

        try {
            const res = await fetch('/api/generate-simc', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    base_profile: parsedData.base_profile,
                    char_class: parsedData.char_class,
                    char_name: parsedData.char_name,
                    equipped_gear: parsedData.equipped_gear,
                    selected_items: selectedItems
                })
            });

            const data = await res.json();
            document.getElementById('combination-count').innerHTML = `<p>Generated <strong>${data.combinations}</strong> combinations to simulate.</p>`;
            
            document.getElementById('btn-tab-sim').disabled = false;
            switchTab('tab-sim');
        } catch (e) {
            alert("Error generating simc input.");
            console.error(e);
        } finally {
            btnGenerateSim.disabled = false;
            btnGenerateSim.textContent = "Generate Combinations & Continue";
        }
    });

    // Run Simulation
    btnRunSim.addEventListener('click', () => {
        btnRunSim.disabled = true;
        simConsole.innerHTML = "Starting simulation...\n";
        
        const source = new EventSource('/api/run-simulation');
        
        source.onmessage = function(event) {
            const data = JSON.parse(event.data);
            if (data.type === 'log') {
                // Handle in-place line updates for progress bars (sim_helper uses \r)
                if (data.text.includes('\r')) {
                    const lines = simConsole.innerHTML.split('\n');
                    lines[lines.length - 1] = data.text.replace(/\r/g, '');
                    simConsole.innerHTML = lines.join('\n');
                } else {
                    simConsole.innerHTML += data.text + '\n';
                }
                simConsole.scrollTop = simConsole.scrollHeight;
            } else if (data.type === 'exit') {
                source.close();
                btnRunSim.disabled = false;
                
                if (data.code === 0) {
                    simConsole.innerHTML += "\n\nSIMULATION COMPLETE!";
                    
                    // Try to find the report filename and tmp dir in the log
                    const logText = simConsole.innerHTML;
                    const matchReport = logText.match(/report_.*\.html/);
                    const matchTmpDir = logText.match(/Temporary files are in (\/tmp\/simc_[^\s<]+)/);
                    let reportFile = null;

                    if (matchReport) {
                        reportFile = matchReport[0];
                        document.getElementById('report-link').href = `/reports/${reportFile}`;
                        document.getElementById('report-frame').src = `/reports/${reportFile}`;
                        document.getElementById('btn-tab-report').disabled = false;
                        switchTab('tab-report');
                    } else {
                        simConsole.innerHTML += "\nWarning: Could not detect report filename.";
                    }

                    if (matchTmpDir) {
                        const tmpDir = matchTmpDir[1];
                        fetch(`/api/get-results?tmp_dir=${encodeURIComponent(tmpDir)}`)
                            .then(res => res.json())
                            .then(resData => renderResults(resData.results, reportFile))
                            .catch(err => console.error("Error fetching results:", err));
                    }
                } else {
                    simConsole.innerHTML += `\nERROR: Simulation failed with code ${data.code}`;
                }
            }
        };
    });

    async function renderResults(results, reportFile) {
        if (!results || results.length === 0) return;

        let htmlDoc = null;
        if (reportFile) {
            try {
                const res = await fetch(`/reports/${reportFile}`);
                const htmlText = await res.text();
                htmlDoc = new DOMParser().parseFromString(htmlText, 'text/html');
            } catch (e) {
                console.error("Failed to fetch/parse HTML report:", e);
            }
        }

        const wrapper = document.getElementById('results-table-wrapper');
        let html = '<table class="results-table">';
        html += '<thead><tr><th>Rank</th><th>Profile</th><th>DPS</th><th>Diff from Baseline</th><th>Gear</th></tr></thead><tbody>';

        // Find baseline to compare against
        const baseline = results.find(r => r.name.includes('Baseline')) || results[0];
        const baselineGear = baseline.gear || {};

        const mapSlotName = (htmlSlot) => {
            const s = htmlSlot.toLowerCase();
            if (s === 'shoulders') return 'shoulder';
            if (s === 'wrists') return 'wrist';
            if (s === 'finger 1') return 'finger1';
            if (s === 'finger 2') return 'finger2';
            if (s === 'trinket 1') return 'trinket1';
            if (s === 'trinket 2') return 'trinket2';
            if (s === 'main hand') return 'main_hand';
            if (s === 'off hand') return 'off_hand';
            return s;
        };

        results.forEach((res, index) => {
            const isBaseline = res.name === baseline.name;
            const dpsDiff = res.dps - baseline.dps;
            const diffClass = dpsDiff > 0 ? 'diff-positive' : (dpsDiff < 0 ? 'diff-negative' : 'diff-neutral');
            const diffText = isBaseline ? '-' : (dpsDiff > 0 ? `+${dpsDiff}` : `${dpsDiff}`);
            const diffPercent = isBaseline ? '-' : ((dpsDiff / baseline.dps) * 100).toFixed(2) + '%';

            let gearHtml = '';
            
            if (htmlDoc) {
                // Find the h2 for this player
                const h2s = Array.from(htmlDoc.querySelectorAll('h2.toggle'));
                const playerH2 = h2s.find(h2 => h2.textContent.includes(res.name));
                
                if (playerH2) {
                    const toggleContent = playerH2.nextElementSibling;
                    if (toggleContent && toggleContent.classList.contains('toggle-content')) {
                        const gearTable = toggleContent.querySelector('.player-section.gear table tbody');
                        if (gearTable) {
                            const rows = gearTable.querySelectorAll('tr');
                            const gearItems = [];
                            for (let i = 0; i < rows.length; i += 2) {
                                const mainRow = rows[i];
                                const statsRow = rows[i+1];
                                if (!mainRow || !statsRow) continue;
                                
                                const slotTh = mainRow.querySelector('th:nth-child(2)');
                                const itemTd = mainRow.querySelector('td');
                                const statsTd = statsRow.querySelector('td.small');
                                
                                if (slotTh && itemTd) {
                                    const slot = slotTh.textContent.trim();
                                    const itemLink = itemTd.innerHTML;
                                    const stats = statsTd ? statsTd.textContent.trim() : '';
                                    
                                    const simcSlot = mapSlotName(slot);
                                    const isDiff = !isBaseline && res.gear && baselineGear && res.gear[simcSlot] !== baselineGear[simcSlot];
                                    const highlightClass = isDiff ? ' gear-diff' : '';
                                    
                                    gearItems.push(`
                                        <div class="gear-item${highlightClass}">
                                            <strong>${slot}:</strong> ${itemLink}
                                            <div style="font-size: 0.75rem; color: var(--text-color); opacity: 0.8; margin-top: 0.2rem;">${stats}</div>
                                        </div>
                                    `);
                                }
                            }
                            gearHtml = gearItems.join('');
                        }
                    }
                }
            }

            if (!gearHtml) {
                if (!isBaseline && res.gear) {
                    const diffs = [];
                    for (const [slot, details] of Object.entries(res.gear)) {
                        if (baselineGear[slot] !== details) {
                            const matchId = details.match(/id=(\d+)/);
                            const itemId = matchId ? matchId[1] : 'Unknown';
                            diffs.push(`<strong>${slot}:</strong> ${itemId}`);
                        }
                    }
                    gearHtml = diffs.length > 0 ? diffs.join('<br>') : '<em>No differences detected or missing gear data.</em>';
                } else if (isBaseline) {
                    gearHtml = '<em>Baseline</em>';
                }
            }

            html += `<tr>
                <td>${index + 1}</td>
                <td><strong>${res.name}</strong></td>
                <td style="font-weight: bold; color: var(--accent-color);">${res.dps.toLocaleString()}</td>
                <td class="${diffClass}">${diffText} (${diffPercent})</td>
                <td style="font-size: 0.85rem; line-height: 1.2;">${gearHtml}</td>
            </tr>`;
        });

        html += '</tbody></table>';
        wrapper.innerHTML = html;
        
        const anchors = wrapper.querySelectorAll('a');
        anchors.forEach(a => {
            a.setAttribute('target', '_blank');
            a.setAttribute('rel', 'noopener noreferrer');
        });

        // Trigger Wowhead tooltips refresh for dynamically added links
        if (typeof $WowheadPower !== 'undefined') {
            $WowheadPower.refreshLinks();
        }
    }
});
