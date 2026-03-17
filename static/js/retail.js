let currentEditingSKU = null;

// Show add modal
function showAddModal() {
    currentEditingSKU = null;
    document.getElementById('modal-title').textContent = 'Add SKU';
    document.getElementById('modal-sku').value = '';
    document.getElementById('modal-sku').disabled = false;
    document.getElementById('modal-product-name').value = '';
    document.getElementById('modal-qty').value = '';
    document.getElementById('modal-notes').value = '';
    document.getElementById('modal').classList.remove('hidden');
}

// Show edit modal
async function editSKU(sku) {
    currentEditingSKU = sku;
    
    try {
        const response = await fetch('/retail/api/skus');
        const skus = await response.json();
        const data = skus[sku];
        
        if (!data) {
            showNotification('SKU not found', 'error');
            return;
        }
        
        document.getElementById('modal-title').textContent = 'Edit SKU';
        document.getElementById('modal-sku').value = sku;
        document.getElementById('modal-sku').disabled = true;
        document.getElementById('modal-product-name').value = data.product_name;
        document.getElementById('modal-qty').value = data.available_qty;
        document.getElementById('modal-notes').value = data.notes || '';
        document.getElementById('modal').classList.remove('hidden');
    } catch (error) {
        showNotification('Error loading SKU data', 'error');
    }
}

// Close modal
function closeModal() {
    document.getElementById('modal').classList.add('hidden');
    currentEditingSKU = null;
}

// Save modal (add or update)
async function saveModal() {
    const sku = document.getElementById('modal-sku').value.trim().toUpperCase();
    const productName = document.getElementById('modal-product-name').value.trim();
    const qty = parseInt(document.getElementById('modal-qty').value);
    const notes = document.getElementById('modal-notes').value.trim();
    
    if (!sku || !productName || isNaN(qty)) {
        showNotification('Please fill in all required fields', 'error');
        return;
    }
    
    const saveBtn = document.getElementById('modal-save-btn');
    saveBtn.disabled = true;
    saveBtn.textContent = 'Saving...';

    try {
        let response;
        
        if (currentEditingSKU) {
            //              Update existing SKU
            response = await fetch(`/retail/api/skus/${currentEditingSKU}`, {
                method: 'PUT',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({
                    product_name: productName,
                    available_qty: qty,
                    notes: notes
                })
            });
        } else {
            //                  Add new SKU
            // find it in Fishbowl and get SN flag
            let validate = await fetch('/retail/api/sku-check', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({
                    sku: sku
                })
            });

            const validated = await validate.json();
            console.log(validated)

            if (!validated.validated_sku) {
                showNotification(validated.message, 'error');
                return;
            } 
            console.log(validated.part_num)

            // add it to config
            response = await fetch('/retail/api/skus', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({
                    sku: sku,
                    product_name: productName,
                    available_qty: qty,
                    notes: notes,
                    sn_flag: validated.is_serialized,
                    part_num: validated.part_num
                })
            });
        }
        
        const result = await response.json();
        
        if (response.ok && result.success) {
            showNotification(currentEditingSKU ? 'SKU updated' : 'SKU added', 'success');
            closeModal();
            location.reload();
        } else {
            showNotification(result.error || 'Error saving SKU', 'error');
        }
    } catch (error) {
        console.log(error)
        showNotification('Error saving SKU', 'error');
    } finally {
        saveBtn.disabled = false;
        saveBtn.textContent = 'Save';
    }
}

// Delete SKU
async function deleteSKU(sku) {
    if (!confirm(`Are you sure you want to delete SKU ${sku}?`)) {
        return;
    }
    
    try {
        const response = await fetch(`/retail/api/skus/${sku}`, {
            method: 'DELETE'
        });
        
        const result = await response.json();
        
        if (response.ok && result.success) {
            showNotification('SKU deleted', 'success');
            location.reload();
        } else {
            showNotification(result.error || 'Error deleting SKU', 'error');
        }
    } catch (error) {
        showNotification('Error deleting SKU', 'error');
    }
}

// Sync now
async function syncNow() {
    const btn = document.getElementById('sync-btn');
    btn.disabled = true;
    btn.textContent = '⏳ Syncing...';
    
    try {
        const response = await fetch('/retail/api/sync', {
            method: 'POST'
        });
        
        const result = await response.json();
        
        if (response.ok && result.success) {
            showNotification(result.message, 'success');
            //setTimeout(() => location.reload(), 10000);
        } else {
            showNotification(result.error || 'Sync failed', 'error');
        }
        updateSyncTime()
    } catch (error) {
        showNotification('Error running sync', 'error');
    } finally {
        btn.disabled = false;
        btn.textContent = '🔄 Sync Now';
    }
}

// Check now
async function checkNow() {
    const btn = document.getElementById('check-btn');
    btn.disabled = true;
    btn.textContent = '⏳ Checking...';
    
    try {
        const response = await fetch('/retail/api/check', {
            method: 'POST'
        });
        
        const result = await response.json();
        
        if (response.ok && result.success) {
            showNotification(result.message, 'success');
            //setTimeout(() => location.reload(), 1500);
        } else {
            showNotification(result.error || 'Sync failed', 'error');
        }
        updateSyncTime()
    } catch (error) {
        showNotification('Error running check', 'error');
    } finally {
        btn.disabled = false;
        btn.textContent = '🔄 Check Now';
    }
}

// Filter table
function filterTable() {
    const input = document.getElementById('search-input').value.toLowerCase();
    const tbody = document.getElementById('sku-tbody');
    const rows = tbody.getElementsByTagName('tr');
    
    for (let row of rows) {
        const sku = row.getAttribute('data-sku').toLowerCase();
        const productName = row.cells[1].textContent.toLowerCase();
        
        if (sku.includes(input) || productName.includes(input)) {
            row.style.display = '';
        } else {
            row.style.display = 'none';
        }
    }
}

// Show notification
function showNotification(message, type = 'info') {
    const colors = {
        success: 'bg-green-500',
        error: 'bg-red-500',
        info: 'bg-blue-500'
    };
    
    const notification = document.createElement('div');
    notification.className = `fixed top-4 right-4 ${colors[type]} text-white px-6 py-3 rounded shadow-lg z-50`;
    notification.textContent = message;
    
    document.body.appendChild(notification);
    
    setTimeout(() => {
        notification.remove();
    }, 10000);
}

// Update sync time display
function updateSyncTime() {
    updateTimeDisplay('sync-time', 'last-sync-display');
    updateTimeDisplay('check-time', 'last-check-display');
    updateTimeDisplay('auto-sync-time', 'auto-sync-time-display'); 
    updateIntervalDisplay();
}

// updates the displayed sync interval. 
async function updateIntervalDisplay() {
    try {
        // Save config
        const response = await fetch('/retail/api/config', {
            method: 'PUT',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({sync_interval_minutes: interval})
        });

        const result = await response.json();

        if (response.ok && result.success) {
            document.getElementById('current-interval-display').textContent = `${interval} min`;

            // Update the automated mode display message
            const autoSyncMessage = document.getElementById('auto-sync-interval-message');
            if (autoSyncMessage) {
                autoSyncMessage.textContent = `Automated sync runs every ${interval} minutes`;
            }
        }
    } catch (error) {
        //
    }
}

// Generic function to update any time display
function updateTimeDisplay(timeElementId, displayElementId) {
    const syncTimeEl = document.getElementById(timeElementId);
    if (!syncTimeEl) return;
    
    const syncTime = syncTimeEl.textContent;
    if (!syncTime || syncTime === 'Never') return;
    
    const date = new Date(syncTime);
    const now = new Date();
    const diffMinutes = Math.floor((now - date) / 60000);
    
    let displayText;
    if (diffMinutes < 1) {
        displayText = 'Just now';
    } else if (diffMinutes < 60) {
        displayText = `${diffMinutes}m ago`;
    } else {
        const hours = Math.floor(diffMinutes / 60);
        displayText = `${hours}h ago`;
    }
    
    document.getElementById(displayElementId).innerHTML = `<span class="status-indicator status-active"></span>${displayText}`;
}

// Auto-refresh sync time every minute
setInterval(updateSyncTime, 60000);
updateSyncTime();

// Auto-refresh data every minute without full page reload
setInterval(async function() {
    console.log('=== Starting data refresh ===');
    
    try {
        // Fetch fresh SKU data
        const response = await fetch('/retail/api/skus');
        const skus = await response.json();
        
        // Fetch fresh config
        const configResponse = await fetch('/retail/api/config');
        const config = await configResponse.json();
        
        // Update last sync times
        if (config.last_sync_run) {
            const syncTimeEl = document.getElementById('sync-time');
            if (syncTimeEl) {
                syncTimeEl.textContent = config.last_sync_run;
            }
        }
        
        if (config.last_check_run) {
            const checkTimeEl = document.getElementById('check-time');
            if (checkTimeEl) {
                checkTimeEl.textContent = config.last_check_run;
            }
        }
        
        const autoSyncTimeEl = document.getElementById('auto-sync-time');
        if (autoSyncTimeEl && config.last_sync_run) {
            autoSyncTimeEl.textContent = config.last_sync_run;
        }
        
        // Update the time displays
        updateSyncTime();
        
        // Update SKU quantities in the table
        const rows = document.querySelectorAll('#sku-tbody tr');
        console.log('Found rows:', rows.length);
        
        rows.forEach(row => {
            const sku = row.getAttribute('data-sku');
            console.log('Processing SKU:', sku);
            
            if (skus[sku]) {
                const qtyDisplay = row.querySelector('.qty-display');
                
                if (qtyDisplay) {
                    const oldQty = qtyDisplay.textContent;
                    const newQty = skus[sku].available_qty;
                    
                    qtyDisplay.textContent = newQty;
                    
                    // Update color based on quantity
                    qtyDisplay.classList.remove('text-red-600', 'text-yellow-600', 'text-green-600');
                    if (newQty <= 0) {
                        qtyDisplay.classList.add('text-red-600');
                    } else if (newQty <= 10) {
                        qtyDisplay.classList.add('text-yellow-600');
                    } else {
                        qtyDisplay.classList.add('text-green-600');
                    }
                }
            } else {
                console.log(`SKU ${sku} not found in fetched data`);
            }
        });
        
        console.log('✅ Data refreshed at', new Date().toLocaleTimeString());
        
    } catch (error) {
        console.error('❌ Error refreshing data:', error);
    }
}, 60000); // 60000ms = 1 minute

// Close modal on ESC key
document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') {
        closeModal();
    }
});

// Inventory method state (stored in browser and backend)
let isManualMode = localStorage.getItem('inventoryMethod') !== 'automated'; // Default manual

// Initialize on page load
document.addEventListener('DOMContentLoaded', function() {
    initializeInventoryMethod();
});

async function initializeInventoryMethod() {
    // Check backend for saved state
    try {
        const response = await fetch('/retail/api/config');
        const config = await response.json();
        
        if (config.inventory_method) {
            isManualMode = config.inventory_method === 'manual';
            localStorage.setItem('inventoryMethod', config.inventory_method);
        }
    } catch (error) {
        console.error('Error loading inventory method:', error);
    }
    
    updateInventoryMethodUI();
}

// Manual or Auto inventory method toggle.
async function toggleInventoryMethod() {
    isManualMode = !isManualMode;
    const method = isManualMode ? 'manual' : 'automated';
    
    // update methods in config
    localStorage.setItem('inventoryMethod', method);
    saveInventoryMethod(method);
    // hide UI as needed
    updateInventoryMethodUI();

    // adjust the schedulers as needed
    let rescheduleSuccess = 1
    try {
        // removing the manual job if switching to automated.
        
        if (method == 'automated') {
            const response = await fetch('/retail/api/remove-job', {
                method: 'POST'
            });
            
            const result = await response.json();
            
            if (!response.ok || !result.success) {
                rescheduleSuccess = 0
            };
        };
        
        // adding the manual job back if switching to manual.
        if (method == 'manual') {
            const response = await fetch('/retail/api/reschedule-sales', {
                method: 'POST'
            });
            
            const result = await response.json();
            
            if (!response.ok || !result.success) {
                rescheduleSuccess = 0
            };
        };

        // reschedule the sync job regardless.
        let rescheduleResponse = await fetch('/retail/api/reschedule-sync', {
            method: 'POST'
        });
        
        if (rescheduleResponse.ok && rescheduleSuccess == 1) {
            showNotification(`Scheduled jobs updated and inventory method set!`, 'success');
        } else if (rescheduleSuccess == 0 && !rescheduleResponse.ok) {
            showNotification(`Failed to remove the manual sales job and reschedule the sync job. Inventory method set.`, 'info');
        } else if (rescheduleSuccess == 0) {
            showNotification(`Failed to remove the manual sales job. The sync job was rescheduled. Method was set.`, 'info');
        } else {
            showNotification(`ERROR: Failed to reschedule the sync job. The manual sales job was removed. Method was set.`, 'info');
        };
    } catch (error) {
        showNotification('Error switching methods: ' + error, 'error');
    };
}

function updateInventoryMethodUI() {
    const toggleBtn = document.getElementById('inventory-method-toggle');
    const toggleLabel = document.getElementById('inventory-method-label');
    const toggleCircle = toggleBtn.querySelector('span');
    const manualUI = document.getElementById('manual-inventory-ui');
    const manualUIAlt = document.getElementById('manual-inventory-ui-alt');
    const automatedUI = document.getElementById('automated-inventory-ui');
    const syncSettings = document.getElementById('sync_section');
    
    if (isManualMode) {
        // Manual mode - show UI
        toggleBtn.classList.remove('bg-gray-400');
        toggleBtn.classList.add('bg-blue-500');
        toggleCircle.classList.add('translate-x-9');
        toggleCircle.classList.remove('translate-x-1');
        toggleLabel.textContent = 'Manual';
        toggleLabel.classList.remove('text-gray-600');
        toggleLabel.classList.add('text-blue-600');
        
        manualUI.classList.remove('hidden');
        automatedUI.classList.add('hidden');
        manualUIAlt.classList.remove('hidden');

        syncSettings.classList.remove('lg:grid-cols-1')
        syncSettings.classList.add('lg:grid-cols-2')
    } else {
        // Automated mode - hide UI
        toggleBtn.classList.remove('bg-blue-500');
        toggleBtn.classList.add('bg-gray-400');
        toggleCircle.classList.remove('translate-x-9');
        toggleCircle.classList.add('translate-x-1');
        toggleLabel.textContent = 'Automated';
        toggleLabel.classList.remove('text-blue-600');
        toggleLabel.classList.add('text-gray-600');
        
        manualUI.classList.add('hidden');
        manualUIAlt.classList.add('hidden');
        automatedUI.classList.remove('hidden');

        syncSettings.classList.remove('lg:grid-cols-2')
        syncSettings.classList.add('lg:grid-cols-1')
    }
}

async function saveInventoryMethod(method) {
    try {
        const response = await fetch('/retail/api/config', {
            method: 'PUT',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({inventory_method: method})
        });
        
        if (!response.ok) {
            throw new Error('Failed to save inventory method');
        }
    } catch (error) {
        console.error('Error saving inventory method:', error);
        showNotification('Error saving inventory method', 'error');
    }
}

// Helper function to check current mode (you can use this in your code)
function isManualInventoryMode() {
    return isManualMode;
}

// same as above
function isAutomatedInventoryMode() {
    return !isManualMode;
}

// Settings panel toggle
function toggleSettings() {
    const content = document.getElementById('settings-content');
    const arrow = document.getElementById('settings-arrow');
    
    if (content.classList.contains('hidden')) {
        content.classList.remove('hidden');
        arrow.classList.add('rotate-180');
    } else {
        content.classList.add('hidden');
        arrow.classList.remove('rotate-180');
    }
}

// Track previous sync interval value
let previousSyncInterval = null;

// Save sync interval
async function saveSyncInterval() {
    const input = document.getElementById('sync-interval-input');
    const interval = parseInt(input.value);

    if (!interval || interval < 1 || interval > 180) {
        showNotification('Please enter a valid interval (1-180 minutes)', 'error');
        return;
    }

    // Check if we're crossing from safe range (3-5) to unsafe range (<3 or >5)
    const isCurrentValueSafe = previousSyncInterval >= 3 && previousSyncInterval <= 5;
    const isNewValueUnsafe = interval < 3 || interval > 5;

    if (isCurrentValueSafe && isNewValueUnsafe) {
        // Show confirmation dialog
        const confirmed = confirm('Changing the sync cycle to this range could have unexpected effects to website inventory functionality.\n\nDo you want to continue?');

        if (!confirmed) {
            // Revert to previous value
            input.value = previousSyncInterval;
            showNotification('Sync interval change cancelled', 'info');
            return;
        }
    }

    const saveBtn = document.getElementById('save-interval-btn');
    saveBtn.disabled = true;
    saveBtn.textContent = 'Saving...';

    try {
        // Save config
        const response = await fetch('/retail/api/config', {
            method: 'PUT',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({sync_interval_minutes: interval})
        });

        const result = await response.json();

        if (response.ok && result.success) {
            // Reschedule sync job
            let rescheduleResponse = await fetch('/retail/api/reschedule-sync', {
                method: 'POST'
            });

            if (rescheduleResponse.ok) {
                showNotification(`Sync interval updated to ${interval} minutes and applied!`, 'success');
            } else {
                showNotification(`Interval saved. Restart server to apply changes.`, 'info');
            }

            document.getElementById('current-interval-display').textContent = `${interval} min`;

            // Update the automated mode display message
            const autoSyncMessage = document.getElementById('auto-sync-interval-message');
            if (autoSyncMessage) {
                autoSyncMessage.textContent = `Automated sync runs every ${interval} minutes`;
            }

            // Update previous value to current value after successful save
            previousSyncInterval = interval;
        } else {
            showNotification(result.error || 'Error saving interval', 'error');
        }
    } catch (error) {
        showNotification('Error saving sync interval', 'error');
    } finally {
        saveBtn.disabled = false;
        saveBtn.textContent = 'Save';
    }
}

// Save sales check interval
async function saveSalesInterval() {
    const input = document.getElementById('sales-interval-input');
    const interval = parseInt(input.value);
    
    if (!interval || interval < 1 || interval > 180) {
        showNotification('Please enter a valid interval (1-180 minutes)', 'error');
        return;
    }
    
    const saveBtn = document.getElementById('save-sales-interval-btn');
    saveBtn.disabled = true;
    saveBtn.textContent = 'Saving...';
    
    try {
        // Save config
        const response = await fetch('/retail/api/config', {
            method: 'PUT',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({sales_interval_minutes: interval})
        });
        
        const result = await response.json();
        
        if (response.ok && result.success) {
            // Reschedule sync job

            let rescheduleResponse = await fetch('/retail/api/reschedule-sales', {
                method: 'POST'
            });
            
            if (rescheduleResponse.ok) {
                showNotification(`Sales check interval updated to ${interval} minutes and applied!`, 'success');
            } else {
                showNotification(`Interval saved. Restart server to apply changes.`, 'info');
            }
            
            document.getElementById('current-sales-interval-display').textContent = `${interval} min`;
        } else {
            showNotification(result.error || 'Error saving interval', 'error');
        }
    } catch (error) {
        showNotification('Error saving sales check interval', 'error');
    } finally {
        saveBtn.disabled = false;
        saveBtn.textContent = 'Save';
    }
}

// Keyboard shortcut: Enter key to save (settings sync interval input)
document.addEventListener('DOMContentLoaded', function() {
    const intervalInput = document.getElementById('sync-interval-input');
    if (intervalInput) {
        // Initialize previous value from current input value
        previousSyncInterval = parseInt(intervalInput.value);

        // Capture previous value when user starts editing
        intervalInput.addEventListener('focus', function() {
            previousSyncInterval = parseInt(intervalInput.value);
        });

        // Enter key to save
        intervalInput.addEventListener('keypress', function(e) {
            if (e.key === 'Enter') {
                saveSyncInterval();
            }
        });
    }

    // Initialize error log display
    refreshErrors();
    // Initialize audit log display
    refreshLogs();
});

// Error Log Functions

// Fetch and display errors
async function refreshErrors() {
    try {
        const response = await fetch('/retail/api/errors?limit=20&unresolved_only=false');
        const result = await response.json();

        if (response.ok && result.success) {
            displayErrors(result.errors);

            // Update error count badge
            const unresolved = result.errors.filter(e => !e.resolved).length;
            document.getElementById('error-count-badge').textContent = unresolved;
        } else {
            console.error('Failed to fetch errors:', result.error);
        }
    } catch (error) {
        console.error('Error fetching error logs:', error);
    }
}

// Display errors in the container
function displayErrors(errors) {
    const container = document.getElementById('error-log-container');

    if (!errors || errors.length === 0) {
        container.innerHTML = `
            <div class="text-center text-gray-500 py-4">
                <span class="text-sm">✅ No errors logged</span>
            </div>
        `;
        return;
    }

    let html = '<div class="space-y-2">';

    errors.forEach(error => {
        const timestamp = new Date(error.timestamp);
        const timeAgo = getTimeAgo(timestamp);
        const isResolved = error.resolved;

        html += `
            <div class="border rounded p-3 ${isResolved ? 'bg-gray-50 opacity-60' : 'bg-red-50 border-red-200'}">
                <div class="flex justify-between items-start">
                    <div class="flex-1">
                        <div class="flex items-center gap-2 mb-1">
                            <span class="text-xs font-bold ${isResolved ? 'text-gray-600' : 'text-red-600'} uppercase">
                                ${error.error_type}
                            </span>
                            ${isResolved ? '<span class="text-xs bg-green-500 text-white px-2 py-0.5 rounded">RESOLVED</span>' : ''}
                        </div>
                        <div class="text-sm text-gray-800 mb-1">
                            ${escapeHtml(error.message)}
                        </div>
                        <div class="text-xs text-gray-500">
                            <span class="font-semibold">Source:</span> ${error.source} |
                            <span class="font-semibold">Time:</span> ${timeAgo} |
                            <span class="font-semibold">ID:</span> ${error.id}
                        </div>
                    </div>
                    <div class="flex gap-1 ml-2">
                        ${!isResolved ? `
                            <button onclick="resolveError(${error.id})"
                                    class="text-green-600 hover:text-green-800 text-xs font-bold px-2 py-1 border border-green-600 rounded hover:bg-green-50 transition"
                                    title="Mark as resolved">
                                ✓
                            </button>
                        ` : ''}
                        <button onclick="toggleErrorDetails(${error.id})"
                                class="text-blue-600 hover:text-blue-800 text-xs font-bold px-2 py-1 border border-blue-600 rounded hover:bg-blue-50 transition"
                                title="Show details">
                            ⓘ
                        </button>
                    </div>
                </div>
                <div id="error-details-${error.id}" class="hidden mt-2 pt-2 border-t border-gray-300">
                    <div class="text-xs text-gray-600">
                        <div><span class="font-semibold">User:</span> ${error.user}</div>
                        <div><span class="font-semibold">Full Timestamp:</span> ${timestamp.toLocaleString()}</div>
                        ${error.details && Object.keys(error.details).length > 0 ? `
                            <div class="mt-1">
                                <span class="font-semibold">Details:</span>
                                <pre class="mt-1 text-xs bg-gray-100 p-2 rounded overflow-x-auto">${JSON.stringify(error.details, null, 2)}</pre>
                            </div>
                        ` : ''}
                    </div>
                </div>
            </div>
        `;
    });

    html += '</div>';
    container.innerHTML = html;
}

// Toggle error details visibility
function toggleErrorDetails(errorId) {
    const detailsEl = document.getElementById(`error-details-${errorId}`);
    if (detailsEl) {
        detailsEl.classList.toggle('hidden');
    }
}

// Mark error as resolved
async function resolveError(errorId) {
    if (!confirm('Mark this error as resolved?')) {
        return;
    }

    try {
        const response = await fetch(`/api/errors/${errorId}/resolve`, {
            method: 'POST'
        });

        const result = await response.json();

        if (response.ok && result.success) {
            showNotification('Error marked as resolved', 'success');
            refreshErrors();
        } else {
            showNotification(result.error || 'Failed to resolve error', 'error');
        }
    } catch (error) {
        showNotification('Error resolving error', 'error');
    }
}

// Clear all errors
async function clearAllErrors() {
    if (!confirm('Are you sure you want to clear ALL error logs? This cannot be undone.')) {
        return;
    }

    try {
        const response = await fetch('/retail/api/errors/clear', {
            method: 'POST'
        });

        const result = await response.json();

        if (response.ok && result.success) {
            showNotification(`Cleared ${result.count} errors`, 'success');
            refreshErrors();
        } else {
            showNotification(result.error || 'Failed to clear errors', 'error');
        }
    } catch (error) {
        showNotification('Error clearing error logs', 'error');
    }
}

// Audit Log Functions

// Fetch and display logs
async function refreshLogs() {
    try {
        const response = await fetch('/retail/api/logs?limit=20');
        const result = await response.json();

        if (response.ok && result.success) {
            displayLogs(result.logs);

            // Update error count badge
            const all = result.logs.length;
            document.getElementById('log-count-badge').textContent = all;
        } else {
            console.error('Failed to fetch logs:', result.error);
        }
    } catch (error) {
        console.error('Error fetching audit logs:', error);
    }
}

// Display audit log in the container
function displayLogs(logs) {
    const container = document.getElementById('audit-log-container');

    if (!logs || logs.length === 0) {
        container.innerHTML = `
            <div class="text-center text-gray-500 py-4">
                <span class="text-sm">✅ No audit log entries</span>
            </div>
        `;
        return;
    }

    let html = '<div class="space-y-2">';

    logs.forEach(log => {
        const timestamp = new Date(log.timestamp);
        const timeAgo = getTimeAgo(timestamp);
        const isResolved = false;
        let logData = log.data;
        if (!logData) {
            logData = log.updates;
        };  
        let logColor = undefined;
        if (log.action == 'delete') {
            logColor = 'red';
        } else if (log.action == 'add') {
            logColor = 'green';
        } else if (log.action == 'update') {
            logColor = 'yellow';
        } else {
            logColor = 'gray';
        };

        html += `
            <div class="border rounded p-3 bg-blue-50 border-blue-200">
                <div class="flex justify-between items-start">
                    <div class="flex-1">
                        <div class="flex items-center gap-2 mb-1">
                            <span class="text-xs font-bold text-${logColor}-600 uppercase">
                                ${log.action} ${log.sku}
                            </span>
                        </div>
                        <div class="text-sm text-gray-800 mb-1">
                            ${(log.action).charAt(0).toUpperCase() + (log.action).slice(1)} performed by ${log.user} on ${log.sku}
                        </div>
                        <div class="text-xs text-gray-500">
                            <span class="font-semibold">Time:</span> ${timeAgo} |
                            <span class="font-semibold">ID:</span> ${log.id}
                        </div>
                    </div>
                    <div class="flex gap-1 ml-2">
                        <button onclick="toggleLogDetails(${log.id})"
                                class="text-blue-600 hover:text-blue-800 text-xs font-bold px-2 py-1 border border-blue-600 rounded hover:bg-blue-50 transition"
                                title="Show details">
                            ⓘ
                        </button>
                    </div>
                </div>
                <div id="log-details-${log.id}" class="hidden mt-2 pt-2 border-t border-gray-300">
                    <div class="text-xs text-gray-600">
                        <div><span class="font-semibold">User:</span> ${log.user}</div>
                        <div><span class="font-semibold">Full Timestamp:</span> ${timestamp.toLocaleString()}</div>
                        ${logData && Object.keys(logData).length > 0 ? `
                            <div class="mt-1">
                                <span class="font-semibold">Details:</span>
                                <pre class="mt-1 text-xs bg-gray-100 p-2 rounded overflow-x-auto">${JSON.stringify(logData, null, 2)}</pre>
                            </div>
                        ` : ''}
                    </div>
                </div>
            </div>
        `;
    });

    html += '</div>';
    container.innerHTML = html;
}

// Toggle audit log entry details visibility
function toggleLogDetails(logId) {
    const logDetailsEl = document.getElementById(`log-details-${logId}`);
    if (logDetailsEl) {
        logDetailsEl.classList.toggle('hidden');
    }
}

// Clear all audit log entries
async function clearAllLogs() {
    if (!confirm('Are you sure you want to clear ALL audit logs? This cannot be undone.')) {
        return;
    }

    try {
        const response = await fetch('/retail/api/logs/clear', {
            method: 'POST'
        });

        const result = await response.json();

        if (response.ok && result.success) {
            showNotification(`Cleared ${result.count} audit log entries`, 'success');
            refreshLogs();
        } else {
            showNotification(result.error || 'Failed to clear the audit log', 'error');
        }
    } catch (error) {
        showNotification('Error clearing the audit log', 'error');
    }
}

// Helper: Escape HTML to prevent XSS
function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

// Helper: Get human-readable time ago
function getTimeAgo(date) {
    const now = new Date();
    const diffMs = now - date;
    const diffMins = Math.floor(diffMs / 60000);

    if (diffMins < 1) return 'Just now';
    if (diffMins < 60) return `${diffMins}m ago`;

    const diffHours = Math.floor(diffMins / 60);
    if (diffHours < 24) return `${diffHours}h ago`;

    const diffDays = Math.floor(diffHours / 24);
    return `${diffDays}d ago`;
}

// Auto-refresh errors every minute
setInterval(refreshErrors, 60000);

// Auto-refresh logs every minute
setInterval(refreshLogs, 60000);