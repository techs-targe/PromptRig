/**
 * Prompt Evaluation System - Phase 2 Complete JavaScript
 * Based on specification in docs/req.txt
 */

// Global state
let currentConfig = null;
let currentParameters = [];
let selectedJobId = null;
let selectedBatchJobId = null;
let allProjects = [];
let allDatasets = [];
let currentProjectId = 1;

// Initialize on page load
document.addEventListener('DOMContentLoaded', () => {
    setupTabNavigation();
    loadInitialData();
    setupEventListeners();
});

/**
 * Setup tab navigation
 * Specification: docs/req.txt section 4.1
 */
function setupTabNavigation() {
    const tabButtons = document.querySelectorAll('.tab-button');
    const tabContents = document.querySelectorAll('.tab-content');

    tabButtons.forEach(button => {
        button.addEventListener('click', () => {
            const targetTab = button.getAttribute('data-tab');

            // Remove active class from all
            tabButtons.forEach(btn => btn.classList.remove('active'));
            tabContents.forEach(content => content.classList.remove('active'));

            // Add active class to clicked
            button.classList.add('active');
            document.getElementById(`tab-${targetTab}`).classList.add('active');

            // Load tab-specific data
            loadTabData(targetTab);
        });
    });
}

/**
 * Load initial data for all tabs
 */
async function loadInitialData() {
    try {
        // Load projects
        await loadProjects();

        // Load settings and models
        await loadSettings();

        // Load single execution config
        await loadConfig();

        // Load datasets
        await loadDatasets();

        // Load available models
        await loadAvailableModels();
    } catch (error) {
        // Initialization error - silently continue
    }
}

/**
 * Load data when tab is switched
 */
function loadTabData(tabName) {
    switch (tabName) {
        case 'single':
            loadConfig();
            break;
        case 'batch':
            loadBatchJobs();
            break;
        case 'projects':
            loadProjects();
            break;
        case 'settings':
            loadSettings();
            loadAvailableModels();
            loadJobParallelism();
            break;
        case 'datasets':
            loadDatasets();
            break;
    }
}

/**
 * Setup all event listeners
 */
function setupEventListeners() {
    // Single execution
    document.getElementById('btn-send-once')?.addEventListener('click', () => executePrompt(1));
    document.getElementById('btn-send-repeat')?.addEventListener('click', () => {
        const repeat = parseInt(document.getElementById('repeat-count').value);
        executePrompt(repeat);
    });
    document.getElementById('single-project-select')?.addEventListener('change', onProjectChange);
    document.getElementById('btn-edit-prompt')?.addEventListener('click', showEditPromptModal);
    document.getElementById('btn-edit-parser')?.addEventListener('click', showEditParserModal);
    document.getElementById('btn-reload-single-history')?.addEventListener('click', async () => {
        const projectId = document.getElementById('single-project-select').value;
        if (projectId) {
            await loadConfig(parseInt(projectId));
            // Re-select the previously selected job if any
            if (selectedJobId) {
                selectHistoryItem(selectedJobId);
            }
        }
    });

    // Batch execution
    document.getElementById('btn-batch-execute')?.addEventListener('click', executeBatch);
    document.getElementById('batch-project-select')?.addEventListener('change', onBatchProjectChange);
    document.getElementById('btn-batch-edit-prompt')?.addEventListener('click', showBatchEditPromptModal);
    document.getElementById('btn-batch-edit-parser')?.addEventListener('click', showBatchEditParserModal);
    document.getElementById('btn-reload-batch-history')?.addEventListener('click', async () => {
        const projectId = document.getElementById('batch-project-select').value;
        if (projectId) {
            await loadBatchJobHistory(parseInt(projectId));
            // Re-select the previously selected batch job if any
            if (selectedBatchJobId) {
                selectBatchJob(selectedBatchJobId);
            }
        }
    });

    // Projects
    document.getElementById('btn-create-project')?.addEventListener('click', showCreateProjectModal);

    // Datasets
    document.getElementById('btn-import-dataset')?.addEventListener('click', showImportDatasetModal);

    // Settings
    document.getElementById('btn-save-default-model')?.addEventListener('click', saveDefaultModel);
    document.getElementById('btn-save-default-project')?.addEventListener('click', saveDefaultProject);
    document.getElementById('param-model-select')?.addEventListener('change', loadModelParameters);
    document.getElementById('btn-save-model-params')?.addEventListener('click', saveModelParameters);
    document.getElementById('btn-reset-model-params')?.addEventListener('click', resetModelParameters);

    // Job execution settings
    document.getElementById('btn-save-parallelism')?.addEventListener('click', saveJobParallelism);

    // Job cancellation buttons
    document.getElementById('btn-stop-single')?.addEventListener('click', cancelSingleJob);
    document.getElementById('btn-stop-batch')?.addEventListener('click', cancelBatchJob);

    // Modal overlay click - DO NOT close on outside click (user requested)
    // Removed event listener to prevent accidental modal close
}

// ========== SINGLE EXECUTION TAB ==========

/**
 * Load configuration for single execution
 * Specification: docs/req.txt section 3.2 step 2
 */
async function loadConfig(projectId = null) {
    try {
        // Use provided projectId or currentProjectId, fallback to project 1
        const pid = projectId || currentProjectId || 1;

        // Get project details
        const projectResponse = await fetch(`/api/projects/${pid}`);
        if (!projectResponse.ok) throw new Error(`Failed to load project ${pid}`);
        const project = await projectResponse.json();

        // Get jobs for this project
        const jobsResponse = await fetch(`/api/projects/${pid}/jobs`);
        if (!jobsResponse.ok) throw new Error(`Failed to load jobs for project ${pid}`);
        const allJobs = await jobsResponse.json();

        // Filter single-type jobs
        const singleJobs = allJobs.filter(job => job.job_type === 'single');

        // Parse prompt template to get parameters (same as before)
        const templateMatch = project.prompt_template.match(/{{([^}]+)}}/g);
        const parameters = templateMatch ? templateMatch.map(match => {
            const paramDef = match.slice(2, -2);
            const [name, type] = paramDef.split(':');
            return {
                name: name.trim(),
                type: type?.trim() || 'str',
                html_type: 'text',
                rows: 1
            };
        }) : [];

        // Build config object compatible with existing code
        currentConfig = {
            project_id: project.id,
            project_name: project.name,
            prompt_template: project.prompt_template,
            parameters: parameters,
            recent_jobs: singleJobs,
            available_models: ["azure-gpt-4.1", "openai-gpt-4.1-nano"]
        };

        renderSingleExecutionTab();
    } catch (error) {
        showStatus('設定の読み込みに失敗しました / Failed to load configuration', 'error');
    }
}

function renderSingleExecutionTab() {
    // Render prompt template
    document.getElementById('prompt-template').textContent = currentConfig.prompt_template;

    // Render parameters
    currentParameters = currentConfig.parameters;
    renderParameterInputs();

    // Render history
    renderHistory(currentConfig.recent_jobs);
}

function renderParameterInputs() {
    const container = document.getElementById('parameter-inputs');
    if (!container) return;

    container.innerHTML = '';

    currentParameters.forEach(param => {
        const group = document.createElement('div');
        group.className = 'param-group';

        const label = document.createElement('label');
        label.setAttribute('for', `param-${param.name}`);
        label.textContent = `${param.name} (${param.type})`;

        let input;
        if (param.html_type === 'textarea') {
            input = document.createElement('textarea');
            input.rows = param.rows || 5;  // Default to 5 rows
        } else {
            input = document.createElement('input');
            input.type = param.html_type;

            // Set accept attribute for file inputs
            if (param.accept) {
                input.accept = param.accept;
            }

            // Set placeholder for text inputs
            if (param.placeholder) {
                input.placeholder = param.placeholder;
            }
        }

        input.id = `param-${param.name}`;
        input.name = param.name;
        input.required = true;

        group.appendChild(label);
        group.appendChild(input);
        container.appendChild(group);
    });
}

function renderHistory(jobs) {
    const container = document.getElementById('history-list');
    if (!container) return;

    if (!jobs || jobs.length === 0) {
        container.innerHTML = '<p class="info">履歴がありません / No history</p>';
        return;
    }

    container.innerHTML = jobs.map(job => {
        const createdAt = new Date(job.created_at).toLocaleString('ja-JP');
        const finishedAt = job.finished_at ? new Date(job.finished_at).toLocaleString('ja-JP') : '-';
        const turnaround = job.turnaround_ms ? `${(job.turnaround_ms / 1000).toFixed(1)}s` : 'N/A';
        const itemCount = job.items ? job.items.length : 0;
        const modelName = job.model_name || '-';

        return `
            <div class="history-item" data-job-id="${job.id}" onclick="selectHistoryItem(${job.id})">
                <div class="job-id">Job #${job.id} (${itemCount} items)</div>
                <div class="timestamp">実行: ${createdAt}</div>
                <div class="timestamp">完了: ${finishedAt}</div>
                <div class="turnaround">モデル: ${modelName} | 実行時間: ${turnaround}</div>
                <span class="status ${job.status}">${job.status}</span>
            </div>
        `;
    }).join('');
}

function selectHistoryItem(jobId) {
    selectedJobId = jobId;

    document.querySelectorAll('.history-item').forEach(item => {
        if (parseInt(item.dataset.jobId) === jobId) {
            item.classList.add('selected');
        } else {
            item.classList.remove('selected');
        }
    });

    const job = currentConfig.recent_jobs.find(j => j.id === jobId);
    if (job) {
        displayJobResults(job);
        if (job.items && job.items.length > 0) {
            const params = JSON.parse(job.items[0].input_params);
            populateInputForm(params);
        }
    }
}

function displayJobResults(job, targetContainer = null) {
    // Accept container as parameter to avoid getElementById conflicts between tabs
    // When called from batch tab, container is passed directly
    // When called from single tab (or no param), use default #results-area
    const container = targetContainer || document.getElementById('results-area');

    if (!container) {
        return;
    }

    if (!job.items || job.items.length === 0) {
        container.innerHTML = '<p class="info">結果がありません / No results</p>';
        return;
    }

    // Helper function to escape HTML
    function escapeHtml(unsafe) {
        if (!unsafe) return '';
        return String(unsafe)
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;")
            .replace(/"/g, "&quot;")
            .replace(/'/g, "&#039;");
    }

    // Display progress summary for batch jobs
    let progressSection = '';
    if (job.job_type === 'batch' && job.items && job.items.length > 0) {
        const total = job.items.length;
        const completed = job.items.filter(item => item.status === 'done').length;
        const errors = job.items.filter(item => item.status === 'error').length;
        const pending = job.items.filter(item => item.status === 'pending').length;
        const running = job.items.filter(item => item.status === 'running').length;
        const progressPercent = Math.round((completed + errors) / total * 100);

        progressSection = `
            <div class="result-item" style="background: linear-gradient(135deg, #3498db 0%, #2980b9 100%); color: white; border-left: 5px solid #2ecc71;">
                <div class="item-header" style="color: white; font-size: 1.2rem;">
                    📊 バッチ実行進捗 / Batch Execution Progress
                </div>
                <div style="margin-top: 1rem; background: white; color: #2c3e50; padding: 1rem; border-radius: 4px;">
                    <div style="font-size: 1.1rem; margin-bottom: 0.5rem;">
                        <strong>進捗: ${completed + errors} / ${total} 件完了 (${progressPercent}%)</strong>
                    </div>
                    <div style="display: flex; gap: 1rem; margin-top: 0.5rem; flex-wrap: wrap;">
                        <span style="color: #27ae60;">✓ 成功: ${completed}件</span>
                        <span style="color: #e74c3c;">✗ エラー: ${errors}件</span>
                        ${pending > 0 ? `<span style="color: #95a5a6;">⏳ 待機中: ${pending}件</span>` : ''}
                        ${running > 0 ? `<span style="color: #3498db;">▶ 実行中: ${running}件</span>` : ''}
                    </div>
                    <div style="margin-top: 1rem; background: #ecf0f1; border-radius: 4px; height: 20px; overflow: hidden;">
                        <div style="background: linear-gradient(90deg, #27ae60 0%, #2ecc71 100%); height: 100%; width: ${progressPercent}%; transition: width 0.3s ease;"></div>
                    </div>
                </div>
            </div>
        `;
    }

    // Display merged CSV output for batch jobs and repeated single executions (Priority display)
    let mergedCsvSection = '';
    if (job.merged_csv_output) {
        const escapedCsv = job.merged_csv_output.replace(/'/g, "\\'").replace(/\n/g, '\\n');
        const isBatch = job.job_type === 'batch';
        const title = isBatch ? 'バッチ実行結果 (CSV統合) / Batch Results (Merged CSV)' : 'n回送信結果 (CSV統合) / Repeated Execution Results (Merged CSV)';
        mergedCsvSection = `
            <div class="result-item" style="background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; border-left: 5px solid #f39c12;">
                <div class="item-header" style="color: white; font-size: 1.2rem;">
                    📊 ${title}
                </div>
                <div style="margin-top: 1rem; background: white; color: #2c3e50; padding: 1rem; border-radius: 4px;">
                    <div class="response-box" style="background-color: #f8f9fa; font-family: 'Courier New', monospace; max-height: 400px; overflow-y: auto;">
                        <pre style="white-space: pre-wrap; word-wrap: break-word;">${job.merged_csv_output}</pre>
                    </div>
                    <button onclick="navigator.clipboard.writeText('${escapedCsv}').then(() => alert('統合CSVをクリップボードにコピーしました / Merged CSV copied to clipboard'))"
                            style="margin-top: 1rem; padding: 0.5rem 1.5rem; background: #27ae60; color: white; border: none; border-radius: 4px; cursor: pointer; font-weight: bold;">
                        📋 統合CSVをコピー / Copy Merged CSV
                    </button>
                    <p style="margin-top: 1rem; color: #7f8c8d; font-size: 0.9rem;">
                        ${job.items.length}件の実行結果を統合しました / Merged ${job.items.length} execution results
                    </p>
                </div>
            </div>
            <h3 style="margin-top: 2rem; color: #34495e; border-bottom: 2px solid #ecf0f1; padding-bottom: 0.5rem;">
                個別実行結果 / Individual Results
            </h3>
        `;
    }

    const itemsHtml = job.items.map((item, index) => {
        try {
            const turnaround = item.turnaround_ms ? `${item.turnaround_ms}ms` : 'N/A';
            let content;

            if (item.status === 'error') {
                content = `<div class="error">Error: ${escapeHtml(item.error_message || 'Unknown error')}</div>`;
            } else {
            // Parse the parsed_response if it exists
            let parsedContent = '';
            if (item.parsed_response) {
                try {
                    const parsed = JSON.parse(item.parsed_response);
                    if (parsed.parsed === false) {
                        // No parser configured
                        parsedContent = '';
                    } else {
                        // Check if CSV output is available (priority display)
                        if (parsed.csv_output) {
                            parsedContent = `
                                <div style="margin-top: 1rem;">
                                    <h4 style="color: #27ae60; margin-bottom: 0.5rem;">📊 パーサー結果 (CSV形式) / Parsed Results (CSV):</h4>
                                    <div class="response-box" style="background-color: #e8f8f5; font-family: 'Courier New', monospace;">
                                        <pre style="white-space: pre-wrap; word-wrap: break-word;">${parsed.csv_output}</pre>
                                    </div>
                                    <button onclick="navigator.clipboard.writeText('${parsed.csv_output.replace(/'/g, "\\'")}').then(() => alert('CSVをクリップボードにコピーしました / CSV copied to clipboard'))"
                                            style="margin-top: 0.5rem; padding: 0.5rem 1rem; background: #27ae60; color: white; border: none; border-radius: 4px; cursor: pointer;">
                                        📋 CSVをコピー / Copy CSV
                                    </button>
                                    <details style="margin-top: 0.5rem;">
                                        <summary style="cursor: pointer; color: #7f8c8d;">フィールド詳細を表示 / Show Field Details</summary>
                                        <pre style="margin-top: 0.5rem;">${JSON.stringify(parsed.fields || {}, null, 2)}</pre>
                                    </details>
                                </div>
                            `;
                        } else {
                            // Check if this is score data (many numeric fields)
                            const fields = parsed.fields || parsed;
                            const isScoreData = Object.values(fields).every(v =>
                                typeof v === 'number' || (typeof v === 'string' && !isNaN(v))
                            );

                            if (isScoreData && Object.keys(fields).length > 5) {
                                // Display as compact table for scores
                                const scoreRows = Object.entries(fields).map(([key, value]) =>
                                    `<span style="display: inline-block; margin: 0.2rem 0.5rem; padding: 0.2rem 0.5rem; background: white; border-radius: 3px;"><strong>${key}:</strong> ${value}</span>`
                                ).join('');

                                parsedContent = `
                                    <div style="margin-top: 1rem;">
                                        <h4 style="color: #27ae60; margin-bottom: 0.5rem;">📊 パーサー結果 (スコア一覧) / Parsed Results (Scores):</h4>
                                        <div class="response-box" style="background-color: #e8f8f5; line-height: 2;">
                                            ${scoreRows}
                                        </div>
                                        <details style="margin-top: 0.5rem;">
                                            <summary style="cursor: pointer; color: #7f8c8d;">JSON形式で表示 / Show as JSON</summary>
                                            <pre style="margin-top: 0.5rem;">${JSON.stringify(fields, null, 2)}</pre>
                                        </details>
                                    </div>
                                `;
                            } else {
                                // Display as regular JSON
                                parsedContent = `
                                    <div style="margin-top: 1rem;">
                                        <h4 style="color: #27ae60; margin-bottom: 0.5rem;">📊 パーサー結果 / Parsed Results:</h4>
                                        <div class="response-box" style="background-color: #e8f8f5;">
                                            <pre>${JSON.stringify(fields, null, 2)}</pre>
                                        </div>
                                    </div>
                                `;
                            }
                        }
                    }
                } catch (e) {
                    parsedContent = `<div style="color: #e74c3c; margin-top: 1rem;">パーサーエラー / Parser error: ${e.message}</div>`;
                }
            }

            content = `
                <div>
                    <h4 style="color: #34495e; margin-bottom: 0.5rem;">📤 送信プロンプト / Sent Prompt:</h4>
                    <div class="response-box" style="background-color: #f8f9fa; max-height: 300px; overflow-y: auto;">
                        <pre>${escapeHtml(item.raw_prompt) || 'No prompt'}</pre>
                    </div>

                    <h4 style="color: #2c3e50; margin-top: 1rem; margin-bottom: 0.5rem;">📄 生レスポンス / Raw Response:</h4>
                    <div class="response-box">
                        <pre>${escapeHtml(item.raw_response) || 'No response'}</pre>
                    </div>
                    ${parsedContent}
                </div>
            `;
        }

            return `
                <div class="result-item">
                    <div class="item-header">Result #${index + 1} <span class="status ${item.status}">${item.status}</span></div>
                    <div class="turnaround">Turnaround: ${turnaround}</div>
                    ${content}
                </div>
            `;
        } catch (error) {
            return `
                <div class="result-item">
                    <div class="item-header">Result #${index + 1} <span class="status error">render_error</span></div>
                    <div class="error">レンダリングエラー / Rendering error: ${escapeHtml(error.message)}</div>
                </div>
            `;
        }
    }).join('');

    container.innerHTML = progressSection + mergedCsvSection + itemsHtml;
}

function populateInputForm(params) {
    Object.entries(params).forEach(([name, value]) => {
        const input = document.getElementById(`param-${name}`);
        if (input) input.value = value;
    });
}

async function executePrompt(repeat) {
    const inputParams = {};
    let valid = true;

    // Process parameters (including FILE type)
    for (const param of currentParameters) {
        const input = document.getElementById(`param-${param.name}`);

        if (param.html_type === 'file') {
            // Handle FILE type - convert to Base64
            if (!input || !input.files || input.files.length === 0) {
                valid = false;
                showStatus(`ファイル "${param.name}" を選択してください`, 'error');
                break;
            }

            try {
                const file = input.files[0];
                const base64 = await fileToBase64(file);
                inputParams[param.name] = base64;
            } catch (error) {
                valid = false;
                showStatus(`ファイル "${param.name}" の読み込みに失敗しました: ${error.message}`, 'error');
                break;
            }
        } else {
            // Handle other types (text, number, date, etc.)
            if (!input || !input.value.trim()) {
                valid = false;
                showStatus(`パラメータ "${param.name}" を入力してください`, 'error');
                break;
            }
            inputParams[param.name] = input.value;
        }
    }

    if (!valid) return;

    const modelName = document.getElementById('model-select').value;
    const includeCsvHeader = document.getElementById('single-include-csv-header')?.checked ?? true;

    setExecutionState(true);
    showStatus('実行中... / Executing...', 'info');

    // Show stop button
    document.getElementById('btn-stop-single').style.display = 'inline-block';

    try {
        // Get model parameters from system settings
        const paramsResponse = await fetch(`/api/settings/models/${modelName}/parameters`);
        const paramsData = await paramsResponse.json();
        const modelParams = paramsData.active_parameters || {};

        const response = await fetch('/api/run/single', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({
                project_id: currentProjectId || 1,
                input_params: inputParams,
                repeat: repeat,
                model_name: modelName,
                include_csv_header: includeCsvHeader,
                ...modelParams  // Include all model parameters from system settings
            })
        });

        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.detail || 'Execution failed');
        }

        const result = await response.json();

        // Store job ID for cancellation
        currentSingleJobId = result.job_id;

        if (result.success) {
            showStatus(`ジョブ開始！ ${result.message}`, 'info');
            displayJobResults(result.job);

            // Restore execution state (but keep stop button visible)
            setExecutionState(false);

            // Start polling for job progress
            pollSingleJobProgress(result.job_id, currentProjectId);
        }
    } catch (error) {
        showStatus(`エラー / Error: ${error.message}`, 'error');
        setExecutionState(false);
        // Hide stop button on error
        document.getElementById('btn-stop-single').style.display = 'none';
        currentSingleJobId = null;
    }
}

// Poll single job progress until completion
let singlePollIntervalId = null;

async function pollSingleJobProgress(jobId, projectId) {
    // Clear any existing polling interval
    if (singlePollIntervalId) {
        clearInterval(singlePollIntervalId);
    }

    // Poll every 3 seconds
    singlePollIntervalId = setInterval(async () => {
        try {
            // Fetch updated job data
            const response = await fetch(`/api/projects/${projectId}/jobs`);
            const allJobs = await response.json();
            const job = allJobs.find(j => j.id === jobId);

            if (!job) {
                // Job not found, stop polling
                clearInterval(singlePollIntervalId);
                singlePollIntervalId = null;
                hideSingleStopButton();
                return;
            }

            // Update display with latest job data
            displayJobResults(job);

            // Check if job is complete
            const isComplete = job.status === 'done' || job.status === 'error';
            const allItemsComplete = job.items && job.items.every(item =>
                item.status === 'done' || item.status === 'error' || item.status === 'cancelled'
            );

            if (isComplete || allItemsComplete) {
                // Job finished, stop polling
                clearInterval(singlePollIntervalId);
                singlePollIntervalId = null;
                hideSingleStopButton();

                // Show completion status
                const completedCount = job.items.filter(i => i.status === 'done').length;
                const errorCount = job.items.filter(i => i.status === 'error').length;
                showStatus(`実行完了！ ${completedCount} 成功, ${errorCount} エラー`, 'success');

                // Reload history to show final status
                await loadConfig();
                selectHistoryItem(jobId);
            }
        } catch (error) {
            console.error('Error polling single job:', error);
            // Continue polling on error (network issue might be temporary)
        }
    }, 3000); // Poll every 3 seconds
}

function hideSingleStopButton() {
    document.getElementById('btn-stop-single').style.display = 'none';
    currentSingleJobId = null;
}

function setExecutionState(executing) {
    const btnOnce = document.getElementById('btn-send-once');
    const btnRepeat = document.getElementById('btn-send-repeat');
    if (btnOnce) btnOnce.disabled = executing;
    if (btnRepeat) btnRepeat.disabled = executing;
}

/**
 * Convert File object to Base64 string with data URL format
 * @param {File} file - The file to convert
 * @returns {Promise<string>} - Base64 encoded data URL (e.g., "data:image/jpeg;base64,...")
 */
function fileToBase64(file) {
    return new Promise((resolve, reject) => {
        const reader = new FileReader();

        reader.onload = () => {
            // reader.result contains the data URL (data:image/jpeg;base64,...)
            resolve(reader.result);
        };

        reader.onerror = () => {
            reject(new Error('Failed to read file'));
        };

        // Read file as data URL (includes Base64 encoding)
        reader.readAsDataURL(file);
    });
}

function showStatus(message, type) {
    const statusDiv = document.getElementById('execution-status');
    if (!statusDiv) return;

    statusDiv.textContent = message;
    statusDiv.className = `status-message ${type} show`;

    if (type === 'success') {
        setTimeout(() => statusDiv.classList.remove('show'), 5000);
    }
}

async function onProjectChange(e) {
    // Handle both event-triggered and manual calls
    if (e && e.target) {
        currentProjectId = parseInt(e.target.value);
    } else {
        // Manual call - get from dropdown
        const singleSelect = document.getElementById('single-project-select');
        if (singleSelect) {
            currentProjectId = parseInt(singleSelect.value);
        }
    }
    await loadConfig();
}

/**
 * Show edit prompt modal
 * Specification: docs/req.txt section 4.4.3 (Revision Management)
 */
async function showEditPromptModal() {
    try {
        const response = await fetch(`/api/projects/${currentProjectId}`);
        if (!response.ok) throw new Error('Failed to load project');
        const project = await response.json();

        const modalContent = `
            <div class="modal-header">プロンプトテンプレート編集 / Edit Prompt Template</div>
            <div class="modal-body">
                <div class="form-group">
                    <label>プロジェクト / Project: ${project.name}</label>
                </div>
                <div class="form-group">
                    <label>プロンプトテンプレート / Prompt Template:</label>
                    <textarea id="edit-prompt-template" rows="15" style="font-family: 'Courier New', monospace;">${project.prompt_template}</textarea>
                    <small style="color: #7f8c8d; display: block; margin-top: 0.5rem;">
                        {{PARAM_NAME}} または {{PARAM_NAME:TYPE}} の形式で入力パラメータを定義<br>
                        <strong>サポートされているTYPE / Supported TYPEs:</strong><br>
                        • TEXT5 (5行テキストエリア / 5-line textarea) - デフォルト<br>
                        • TEXT10 (10行テキストエリア / 10-line textarea)<br>
                        • NUM (数値入力 / Number input)<br>
                        • DATE (日付選択 / Date picker)<br>
                        • DATETIME (日時選択 / DateTime picker)<br>
                        • <strong>FILE</strong> (画像アップロード / Image upload) - Vision API対応<br>
                        • <strong>FILEPATH</strong> (サーバーパス / Server file path) - バッチ処理用
                    </small>
                </div>
            </div>
            <div class="modal-footer">
                <button class="btn btn-secondary" onclick="closeModal()">キャンセル / Cancel</button>
                <button class="btn btn-primary" onclick="savePromptRevision()">保存 / Save</button>
                <button class="btn btn-primary" onclick="rebuildPromptRevision()" style="background-color: #27ae60;">リビルド / Rebuild</button>
            </div>
        `;
        showModal(modalContent);
    } catch (error) {
        alert(`エラー / Error: ${error.message}`);
    }
}

/**
 * Save (update) current prompt revision
 * Specification: docs/req.txt section 4.4.3 - 保存ボタン
 */
async function savePromptRevision() {
    const newTemplate = document.getElementById('edit-prompt-template').value;
    if (!newTemplate.trim()) {
        alert('プロンプトテンプレートを入力してください / Please enter a prompt template');
        return;
    }

    try {
        const response = await fetch(`/api/projects/${currentProjectId}/revisions/latest`, {
            method: 'PUT',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({
                prompt_template: newTemplate
            })
        });

        if (!response.ok) throw new Error('Failed to update revision');

        closeModal();
        await loadConfig();
        alert('プロンプトテンプレートを保存しました / Prompt template saved');
    } catch (error) {
        alert(`エラー / Error: ${error.message}`);
    }
}

/**
 * Rebuild (create new) prompt revision
 * Specification: docs/req.txt section 4.4.3 - リビルドボタン
 */
async function rebuildPromptRevision() {
    const newTemplate = document.getElementById('edit-prompt-template').value;
    if (!newTemplate.trim()) {
        alert('プロンプトテンプレートを入力してください / Please enter a prompt template');
        return;
    }

    if (!confirm('新しいリビジョンを作成しますか？\n{{}}構造の変更を伴う場合に使用してください。\n\nCreate a new revision?\nUse this when changing {{}} structure.')) {
        return;
    }

    try {
        const response = await fetch(`/api/projects/${currentProjectId}/revisions`, {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({
                prompt_template: newTemplate
            })
        });

        if (!response.ok) throw new Error('Failed to create revision');

        closeModal();
        await loadConfig();
        alert('新しいリビジョンを作成しました / New revision created');
    } catch (error) {
        alert(`エラー / Error: ${error.message}`);
    }
}

/**
 * Show edit parser modal
 * Specification: docs/req.txt section 6.2 (Response Parser)
 */
async function showEditParserModal() {
    try {
        const response = await fetch(`/api/projects/${currentProjectId}`);
        if (!response.ok) throw new Error('Failed to load project');
        const project = await response.json();

        const parserConfig = project.parser_config || {type: 'none'};
        const parserJson = JSON.stringify(parserConfig, null, 2);

        const modalContent = `
            <div class="modal-header">
                パーサー設定編集 / Edit Parser Configuration
                <button onclick="showParserHelp()" style="background: none; border: none; cursor: pointer; font-size: 1.2rem; margin-left: 10px;" title="ヘルプを表示 / Show Help">❓</button>
            </div>
            <div class="modal-body">
                <div class="form-group">
                    <label>プロジェクト / Project: ${project.name}</label>
                </div>
                <div class="form-group">
                    <label>パーサータイプ / Parser Type:</label>
                    <select id="edit-parser-type">
                        <option value="none" ${parserConfig.type === 'none' ? 'selected' : ''}>なし / None</option>
                        <option value="json_path" ${parserConfig.type === 'json_path' ? 'selected' : ''}>JSON Path</option>
                        <option value="regex" ${parserConfig.type === 'regex' ? 'selected' : ''}>正規表現 / Regex</option>
                    </select>
                </div>
                <div class="form-group">
                    <label>パーサー設定 (JSON) / Parser Configuration (JSON):</label>
                    <textarea id="edit-parser-config" rows="12" style="font-family: 'Courier New', monospace;">${parserJson}</textarea>
                    <small style="color: #7f8c8d;">
                        JSON Path例: {"type": "json_path", "paths": {"answer": "$.answer"}}<br>
                        正規表現例: {"type": "regex", "patterns": {"answer": "Answer: (.+)"}}
                    </small>
                </div>
            </div>
            <div class="modal-footer">
                <button class="btn btn-secondary" onclick="closeModal()">キャンセル / Cancel</button>
                <button class="btn btn-primary" onclick="saveParserRevision()">保存 / Save</button>
                <button class="btn btn-primary" onclick="rebuildParserRevision()" style="background-color: #27ae60;">リビルド / Rebuild</button>
            </div>
        `;
        showModal(modalContent);
    } catch (error) {
        alert(`エラー / Error: ${error.message}`);
    }
}

/**
 * Save (update) current parser revision
 * Specification: docs/req.txt section 4.4.3 - 保存ボタン
 */
async function saveParserRevision() {
    const parserType = document.getElementById('edit-parser-type').value;
    const parserConfigText = document.getElementById('edit-parser-config').value;

    let parserConfig;
    try {
        parserConfig = JSON.parse(parserConfigText);
        parserConfig.type = parserType; // Ensure type matches selection
    } catch (error) {
        alert('パーサー設定のJSON形式が不正です / Invalid JSON format for parser configuration');
        return;
    }

    try {
        const response = await fetch(`/api/projects/${currentProjectId}/revisions/latest`, {
            method: 'PUT',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({
                parser_config: JSON.stringify(parserConfig)
            })
        });

        if (!response.ok) throw new Error('Failed to update revision');

        closeModal();
        await loadConfig();
        alert('パーサー設定を保存しました / Parser configuration saved');
    } catch (error) {
        alert(`エラー / Error: ${error.message}`);
    }
}

/**
 * Rebuild (create new) parser revision
 * Specification: docs/req.txt section 4.4.3 - リビルドボタン
 */
async function rebuildParserRevision() {
    const parserType = document.getElementById('edit-parser-type').value;
    const parserConfigText = document.getElementById('edit-parser-config').value;

    let parserConfig;
    try {
        parserConfig = JSON.parse(parserConfigText);
        parserConfig.type = parserType; // Ensure type matches selection
    } catch (error) {
        alert('パーサー設定のJSON形式が不正です / Invalid JSON format for parser configuration');
        return;
    }

    if (!confirm('新しいリビジョンを作成しますか？\n\nCreate a new revision?')) {
        return;
    }

    try {
        const response = await fetch(`/api/projects/${currentProjectId}/revisions`, {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({
                parser_config: JSON.stringify(parserConfig)
            })
        });

        if (!response.ok) throw new Error('Failed to create revision');

        closeModal();
        await loadConfig();
        alert('新しいリビジョンを作成しました / New revision created');
    } catch (error) {
        alert(`エラー / Error: ${error.message}`);
    }
}

// ========== BATCH EXECUTION EDIT MODALS ==========

/**
 * Show batch edit prompt modal
 */
async function showBatchEditPromptModal() {
    const projectId = document.getElementById('batch-project-select').value;
    if (!projectId) {
        alert('プロジェクトを選択してください / Please select a project');
        return;
    }

    try {
        const response = await fetch(`/api/projects/${projectId}`);
        if (!response.ok) throw new Error('Failed to load project');
        const project = await response.json();

        const modalContent = `
            <div class="modal-header">プロンプトテンプレート編集 / Edit Prompt Template</div>
            <div class="modal-body">
                <div class="form-group">
                    <label>プロジェクト / Project: ${project.name}</label>
                </div>
                <div class="form-group">
                    <label>プロンプトテンプレート / Prompt Template:</label>
                    <textarea id="edit-prompt-template" rows="15" style="font-family: 'Courier New', monospace;">${project.prompt_template}</textarea>
                    <small style="color: #7f8c8d; display: block; margin-top: 0.5rem;">
                        {{PARAM_NAME}} または {{PARAM_NAME:TYPE}} の形式で入力パラメータを定義<br>
                        <strong>サポートされているTYPE / Supported TYPEs:</strong><br>
                        • TEXT5 (5行テキストエリア / 5-line textarea) - デフォルト<br>
                        • TEXT10 (10行テキストエリア / 10-line textarea)<br>
                        • NUM (数値入力 / Number input)<br>
                        • DATE (日付選択 / Date picker)<br>
                        • DATETIME (日時選択 / DateTime picker)<br>
                        • <strong>FILE</strong> (画像アップロード / Image upload) - Vision API対応<br>
                        • <strong>FILEPATH</strong> (サーバーパス / Server file path) - バッチ処理用
                    </small>
                </div>
            </div>
            <div class="modal-footer">
                <button class="btn btn-secondary" onclick="closeModal()">キャンセル / Cancel</button>
                <button class="btn btn-primary" onclick="saveBatchPromptRevision(${projectId})">保存 / Save</button>
                <button class="btn btn-primary" onclick="rebuildBatchPromptRevision(${projectId})" style="background-color: #27ae60;">リビルド / Rebuild</button>
            </div>
        `;
        showModal(modalContent);
    } catch (error) {
        alert(`エラー / Error: ${error.message}`);
    }
}

/**
 * Save batch prompt revision
 */
async function saveBatchPromptRevision(projectId) {
    const newTemplate = document.getElementById('edit-prompt-template').value;
    if (!newTemplate.trim()) {
        alert('プロンプトテンプレートを入力してください / Please enter a prompt template');
        return;
    }

    try {
        const response = await fetch(`/api/projects/${projectId}/revisions/latest`, {
            method: 'PUT',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({
                prompt_template: newTemplate
            })
        });

        if (!response.ok) throw new Error('Failed to update revision');

        closeModal();
        alert('プロンプトテンプレートを保存しました / Prompt template saved');
    } catch (error) {
        alert(`エラー / Error: ${error.message}`);
    }
}

/**
 * Rebuild batch prompt revision
 */
async function rebuildBatchPromptRevision(projectId) {
    const newTemplate = document.getElementById('edit-prompt-template').value;
    if (!newTemplate.trim()) {
        alert('プロンプトテンプレートを入力してください / Please enter a prompt template');
        return;
    }

    if (!confirm('新しいリビジョンを作成しますか？\n{{}}構造の変更を伴う場合に使用してください。\n\nCreate a new revision?\nUse this when changing {{}} structure.')) {
        return;
    }

    try {
        const response = await fetch(`/api/projects/${projectId}/revisions`, {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({
                prompt_template: newTemplate
            })
        });

        if (!response.ok) throw new Error('Failed to create revision');

        closeModal();
        alert('新しいリビジョンを作成しました / New revision created');
    } catch (error) {
        alert(`エラー / Error: ${error.message}`);
    }
}

/**
 * Show batch edit parser modal
 */
async function showBatchEditParserModal() {
    const projectId = document.getElementById('batch-project-select').value;
    if (!projectId) {
        alert('プロジェクトを選択してください / Please select a project');
        return;
    }

    try {
        const response = await fetch(`/api/projects/${projectId}`);
        if (!response.ok) throw new Error('Failed to load project');
        const project = await response.json();

        const parserConfig = project.parser_config || {type: 'none'};
        const parserJson = JSON.stringify(parserConfig, null, 2);

        const modalContent = `
            <div class="modal-header">
                パーサー設定編集 / Edit Parser Configuration
                <button onclick="showParserHelp()" style="background: none; border: none; cursor: pointer; font-size: 1.2rem; margin-left: 10px;" title="ヘルプを表示 / Show Help">❓</button>
            </div>
            <div class="modal-body">
                <div class="form-group">
                    <label>プロジェクト / Project: ${project.name}</label>
                </div>
                <div class="form-group">
                    <label>パーサータイプ / Parser Type:</label>
                    <select id="edit-parser-type">
                        <option value="none" ${parserConfig.type === 'none' ? 'selected' : ''}>なし / None</option>
                        <option value="json_path" ${parserConfig.type === 'json_path' ? 'selected' : ''}>JSON Path</option>
                        <option value="regex" ${parserConfig.type === 'regex' ? 'selected' : ''}>正規表現 / Regex</option>
                    </select>
                </div>
                <div class="form-group">
                    <label>パーサー設定 (JSON) / Parser Configuration (JSON):</label>
                    <textarea id="edit-parser-config" rows="12" style="font-family: 'Courier New', monospace;">${parserJson}</textarea>
                    <small style="color: #7f8c8d;">
                        JSON Path例: {"type": "json_path", "paths": {"answer": "$.answer"}}<br>
                        正規表現例: {"type": "regex", "patterns": {"answer": "Answer: (.+)"}}
                    </small>
                </div>
            </div>
            <div class="modal-footer">
                <button class="btn btn-secondary" onclick="closeModal()">キャンセル / Cancel</button>
                <button class="btn btn-primary" onclick="saveBatchParserRevision(${projectId})">保存 / Save</button>
                <button class="btn btn-primary" onclick="rebuildBatchParserRevision(${projectId})" style="background-color: #27ae60;">リビルド / Rebuild</button>
            </div>
        `;
        showModal(modalContent);
    } catch (error) {
        alert(`エラー / Error: ${error.message}`);
    }
}

/**
 * Save batch parser revision
 */
async function saveBatchParserRevision(projectId) {
    const parserType = document.getElementById('edit-parser-type').value;
    const parserConfigText = document.getElementById('edit-parser-config').value;

    let parserConfig;
    try {
        parserConfig = JSON.parse(parserConfigText);
        parserConfig.type = parserType;
    } catch (error) {
        alert('パーサー設定のJSON形式が不正です / Invalid JSON format for parser configuration');
        return;
    }

    try {
        const response = await fetch(`/api/projects/${projectId}/revisions/latest`, {
            method: 'PUT',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({
                parser_config: JSON.stringify(parserConfig)
            })
        });

        if (!response.ok) throw new Error('Failed to update revision');

        closeModal();
        alert('パーサー設定を保存しました / Parser configuration saved');
    } catch (error) {
        alert(`エラー / Error: ${error.message}`);
    }
}

/**
 * Rebuild batch parser revision
 */
async function rebuildBatchParserRevision(projectId) {
    const parserType = document.getElementById('edit-parser-type').value;
    const parserConfigText = document.getElementById('edit-parser-config').value;

    let parserConfig;
    try {
        parserConfig = JSON.parse(parserConfigText);
        parserConfig.type = parserType;
    } catch (error) {
        alert('パーサー設定のJSON形式が不正です / Invalid JSON format for parser configuration');
        return;
    }

    if (!confirm('新しいリビジョンを作成しますか？\nパーサー構造の変更を伴う場合に使用してください。\n\nCreate a new revision?\nUse this when changing parser structure.')) {
        return;
    }

    try {
        const response = await fetch(`/api/projects/${projectId}/revisions`, {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({
                parser_config: JSON.stringify(parserConfig)
            })
        });

        if (!response.ok) throw new Error('Failed to create revision');

        closeModal();
        alert('新しいリビジョンを作成しました / New revision created');
    } catch (error) {
        alert(`エラー / Error: ${error.message}`);
    }
}

// ========== BATCH EXECUTION TAB ==========

async function loadBatchJobs() {
    // Load datasets for currently selected project (if any)
    const projectSelect = document.getElementById('batch-project-select');
    if (projectSelect && projectSelect.value) {
        await loadDatasetsForProject(parseInt(projectSelect.value));
        await loadBatchJobHistory(parseInt(projectSelect.value));
    }
}

async function loadBatchJobHistory(projectId) {
    try {
        // Get jobs for this project using new API
        const response = await fetch(`/api/projects/${projectId}/jobs`);
        const allJobs = await response.json();

        // Filter batch jobs only
        const batchJobs = allJobs.filter(job => job.job_type === 'batch');

        renderBatchHistory(batchJobs);
    } catch (error) {
        const container = document.getElementById('batch-jobs-list');
        if (container) {
            container.innerHTML = '<p class="info">バッチジョブの履歴を読み込めませんでした / Failed to load batch job history</p>';
        }
    }
}

let currentBatchJobs = [];

function renderBatchHistory(jobs) {
    const container = document.getElementById('batch-jobs-list');
    if (!container) return;

    // Store jobs for later use
    currentBatchJobs = jobs || [];

    if (!jobs || jobs.length === 0) {
        container.innerHTML = '<p class="info">バッチジョブの履歴はまだありません / No batch jobs yet</p>';
        return;
    }

    container.innerHTML = jobs.map(job => {
        const createdAt = new Date(job.created_at).toLocaleString('ja-JP');
        const finishedAt = job.finished_at ? new Date(job.finished_at).toLocaleString('ja-JP') : '-';
        const turnaround = job.turnaround_ms ? `${(job.turnaround_ms / 1000).toFixed(1)}s` : 'N/A';
        const itemCount = job.items ? job.items.length : 0;
        const modelName = job.model_name || '-';

        return `
            <div class="history-item" data-job-id="${job.id}">
                <div class="job-id">Batch Job #${job.id} (${itemCount} items)</div>
                <div class="timestamp">実行: ${createdAt}</div>
                <div class="timestamp">完了: ${finishedAt}</div>
                <div class="turnaround">モデル: ${modelName} | 実行時間: ${turnaround}</div>
                <span class="status ${job.status}">${job.status}</span>
            </div>
        `;
    }).join('');

    // Add click event listeners after rendering
    document.querySelectorAll('#batch-jobs-list .history-item').forEach(item => {
        item.addEventListener('click', () => {
            const jobId = parseInt(item.dataset.jobId);
            selectBatchJob(jobId);
        });
    });
}

async function selectBatchJob(jobId) {
    try {
        // Save selected job ID for refresh functionality
        selectedBatchJobId = jobId;

        // Find job in current batch jobs list
        const job = currentBatchJobs.find(j => j.id === jobId);

        if (job) {
            displayBatchResult(job);
        }

        // Highlight selected item
        document.querySelectorAll('#batch-jobs-list .history-item').forEach(item => {
            if (parseInt(item.dataset.jobId) === jobId) {
                item.classList.add('selected');
            } else {
                item.classList.remove('selected');
            }
        });
    } catch (error) {
        // Silently handle errors - could log to server if needed
    }
}

function displayBatchResult(job) {
    const container = document.getElementById('batch-results-area');

    if (!container) {
        return;
    }

    // Clear existing content first
    container.innerHTML = '';

    // Pass the batch results container directly to avoid ID conflicts
    // This ensures results display in the batch tab, not the single execution tab
    displayJobResults(job, container);
}

async function executeBatch() {
    const projectId = document.getElementById('batch-project-select').value;
    const datasetId = document.getElementById('batch-dataset-select').value;
    const includeCsvHeader = document.getElementById('batch-include-csv-header')?.checked ?? true;
    const modelName = document.getElementById('batch-model-select').value;

    if (!projectId || !datasetId) {
        alert('プロジェクトとデータセットを選択してください / Please select project and dataset');
        return;
    }

    // Immediate feedback
    const executeBtn = document.getElementById('btn-batch-execute');
    const originalText = executeBtn.textContent;
    executeBtn.disabled = true;
    executeBtn.textContent = '実行中... / Executing...';
    executeBtn.style.background = '#95a5a6';

    // Show stop button
    document.getElementById('btn-stop-batch').style.display = 'inline-block';

    try {
        // Get model parameters from system settings
        const paramsResponse = await fetch(`/api/settings/models/${modelName}/parameters`);
        const paramsData = await paramsResponse.json();
        const modelParams = paramsData.active_parameters || {};

        const response = await fetch('/api/run/batch', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({
                project_id: parseInt(projectId),
                dataset_id: parseInt(datasetId),
                include_csv_header: includeCsvHeader,
                model_name: modelName,
                ...modelParams  // Include all model parameters from system settings
            })
        });

        if (!response.ok) throw new Error('Batch execution failed');

        const result = await response.json();

        // Store job ID for cancellation
        currentBatchJobId = result.job_id;

        // Display results immediately
        displayBatchResult(result.job);

        // Restore execute button (but keep stop button visible)
        executeBtn.disabled = false;
        executeBtn.textContent = originalText;
        executeBtn.style.background = '';

        // Start polling for job progress
        pollBatchJobProgress(result.job_id, parseInt(projectId));

    } catch (error) {
        alert(`エラー / Error: ${error.message}`);
        // On error, restore button and hide stop button
        executeBtn.disabled = false;
        executeBtn.textContent = originalText;
        executeBtn.style.background = '';
        document.getElementById('btn-stop-batch').style.display = 'none';
        currentBatchJobId = null;
    }
}

// Poll batch job progress until completion
let batchPollIntervalId = null;

async function pollBatchJobProgress(jobId, projectId) {
    // Clear any existing polling interval
    if (batchPollIntervalId) {
        clearInterval(batchPollIntervalId);
    }

    // Poll every 3 seconds
    batchPollIntervalId = setInterval(async () => {
        try {
            // Fetch updated job data
            const response = await fetch(`/api/projects/${projectId}/jobs`);
            const allJobs = await response.json();
            const job = allJobs.find(j => j.id === jobId);

            if (!job) {
                // Job not found, stop polling
                clearInterval(batchPollIntervalId);
                batchPollIntervalId = null;
                hideBatchStopButton();
                return;
            }

            // Update display with latest job data
            displayBatchResult(job);

            // Check if job is complete
            const isComplete = job.status === 'done' || job.status === 'error';
            const allItemsComplete = job.items && job.items.every(item =>
                item.status === 'done' || item.status === 'error' || item.status === 'cancelled'
            );

            if (isComplete || allItemsComplete) {
                // Job finished, stop polling
                clearInterval(batchPollIntervalId);
                batchPollIntervalId = null;
                hideBatchStopButton();
                // Reload history to show final status
                await loadBatchJobHistory(projectId);
            }
        } catch (error) {
            console.error('Error polling batch job:', error);
            // Continue polling on error (network issue might be temporary)
        }
    }, 3000); // Poll every 3 seconds
}

function hideBatchStopButton() {
    document.getElementById('btn-stop-batch').style.display = 'none';
    currentBatchJobId = null;
}

async function onBatchProjectChange(e) {
    const projectId = parseInt(e.target.value);
    await loadDatasetsForProject(projectId);
}

async function loadDatasetsForProject(projectId) {
    try {
        const response = await fetch(`/api/datasets?project_id=${projectId}`);
        const datasets = await response.json();

        const select = document.getElementById('batch-dataset-select');
        if (!select) return;

        select.innerHTML = '<option value="">データセットを選択 / Select Dataset</option>' +
            datasets.map(ds => `<option value="${ds.id}">${ds.name} (${ds.row_count} rows)</option>`).join('');
    } catch (error) {
        // Failed to load datasets - silently continue
    }
}

// ========== PROJECTS TAB ==========

async function loadProjects() {
    try {
        const response = await fetch('/api/projects');
        allProjects = await response.json();
        renderProjects();
        await updateProjectSelects();
    } catch (error) {
        // Failed to load projects - silently continue
    }
}

function renderProjects() {
    const container = document.getElementById('projects-list');
    if (!container) return;

    if (allProjects.length === 0) {
        container.innerHTML = '<p class="info">プロジェクトがありません / No projects</p>';
        return;
    }

    container.innerHTML = allProjects.map(project => `
        <div class="list-item">
            <div class="item-header">
                <div class="item-title">${project.name}</div>
                <div class="item-actions">
                    <button class="btn btn-secondary" onclick="editProject(${project.id})">編集 / Edit</button>
                    <button class="btn btn-secondary" onclick="deleteProject(${project.id})">削除 / Delete</button>
                </div>
            </div>
            <div class="item-description">${project.description || ''}</div>
            <div class="item-meta">
                リビジョン数: ${project.revision_count} | 作成日: ${new Date(project.created_at).toLocaleString('ja-JP')}
            </div>
        </div>
    `).join('');
}

async function updateProjectSelects() {
    const singleSelect = document.getElementById('single-project-select');
    const batchSelect = document.getElementById('batch-project-select');
    const defaultProjectSelect = document.getElementById('default-project-select');

    const options = allProjects.map(p => `<option value="${p.id}">${p.name}</option>`).join('');

    if (singleSelect) {
        singleSelect.innerHTML = options;
        // Set default project if configured
        try {
            const response = await fetch('/api/settings/default-project');
            const data = await response.json();
            if (data.project_id) {
                singleSelect.value = data.project_id;
                // Trigger project change to load prompts
                await onProjectChange();
            }
        } catch (error) {
            console.error('Failed to load default project:', error);
        }
    }

    if (batchSelect) {
        batchSelect.innerHTML = options;
        // Set default project if configured
        try {
            const response = await fetch('/api/settings/default-project');
            const data = await response.json();
            if (data.project_id) {
                batchSelect.value = data.project_id;
                // Load datasets for default project
                await loadDatasetsForProject(data.project_id);
            } else if (batchSelect.value) {
                // Auto-load datasets for first project on batch tab if no default
                await loadDatasetsForProject(parseInt(batchSelect.value));
            }
        } catch (error) {
            console.error('Failed to load default project for batch:', error);
            // Fallback to first project
            if (batchSelect.value) {
                await loadDatasetsForProject(parseInt(batchSelect.value));
            }
        }
    }

    if (defaultProjectSelect) {
        defaultProjectSelect.innerHTML = options;
        // Set current default project in settings
        try {
            const response = await fetch('/api/settings/default-project');
            const data = await response.json();
            if (data.project_id) {
                defaultProjectSelect.value = data.project_id;
            }
        } catch (error) {
            console.error('Failed to load default project for settings:', error);
        }
    }
}

function showCreateProjectModal() {
    showModal(`
        <div class="modal-header">新規プロジェクト作成 / Create Project</div>
        <div class="modal-body">
            <div class="form-group">
                <label>プロジェクト名 / Name:</label>
                <input type="text" id="project-name" required>
            </div>
            <div class="form-group">
                <label>説明 / Description:</label>
                <textarea id="project-description" rows="3"></textarea>
            </div>
        </div>
        <div class="modal-footer">
            <button class="btn btn-secondary" onclick="closeModal()">キャンセル / Cancel</button>
            <button class="btn btn-primary" onclick="createProject()">作成 / Create</button>
        </div>
    `);
}

async function createProject() {
    const name = document.getElementById('project-name').value;
    const description = document.getElementById('project-description').value;

    if (!name) {
        alert('プロジェクト名を入力してください / Please enter project name');
        return;
    }

    try {
        const response = await fetch('/api/projects', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({name, description})
        });

        if (!response.ok) throw new Error('Failed to create project');

        closeModal();
        await loadProjects();
        alert('プロジェクトを作成しました / Project created');
    } catch (error) {
        alert(`エラー / Error: ${error.message}`);
    }
}

async function editProject(id) {
    const project = allProjects.find(p => p.id === id);
    if (!project) return;

    showModal(`
        <div class="modal-header">プロジェクト編集 / Edit Project</div>
        <div class="modal-body">
            <div class="form-group">
                <label>プロジェクト名 / Name:</label>
                <input type="text" id="edit-project-name" value="${project.name}" required>
            </div>
            <div class="form-group">
                <label>説明 / Description:</label>
                <textarea id="edit-project-description" rows="3">${project.description || ''}</textarea>
            </div>
        </div>
        <div class="modal-footer">
            <button class="btn btn-secondary" onclick="closeModal()">キャンセル / Cancel</button>
            <button class="btn btn-primary" onclick="updateProject(${id})">更新 / Update</button>
        </div>
    `);
}

async function updateProject(id) {
    const name = document.getElementById('edit-project-name').value;
    const description = document.getElementById('edit-project-description').value;

    try {
        const response = await fetch(`/api/projects/${id}`, {
            method: 'PUT',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({name, description})
        });

        if (!response.ok) throw new Error('Failed to update project');

        closeModal();
        await loadProjects();
        alert('プロジェクトを更新しました / Project updated');
    } catch (error) {
        alert(`エラー / Error: ${error.message}`);
    }
}

async function deleteProject(id) {
    if (!confirm('このプロジェクトを削除しますか？ / Delete this project?')) return;

    try {
        const response = await fetch(`/api/projects/${id}`, {method: 'DELETE'});
        if (!response.ok) throw new Error('Failed to delete project');

        await loadProjects();
        alert('プロジェクトを削除しました / Project deleted');
    } catch (error) {
        alert(`エラー / Error: ${error.message}`);
    }
}

// ========== SYSTEM SETTINGS TAB ==========

async function loadAvailableModels() {
    try {
        const response = await fetch('/api/settings/models/available');
        const models = await response.json();

        const container = document.getElementById('available-models');
        if (!container) return;

        container.innerHTML = models.map(model =>
            `<div class="badge badge-info">${model.display_name || model.name || model}</div>`
        ).join(' ');

        // Also load model enable settings
        await loadModelEnableSettings();
    } catch (error) {
        // Failed to load models - silently continue
    }
}

async function loadModelEnableSettings() {
    try {
        const response = await fetch('/api/settings/models/all');
        const models = await response.json();

        const container = document.getElementById('model-enable-settings');
        if (!container) return;

        container.innerHTML = models.map(model => `
            <div class="model-toggle" style="display: flex; align-items: center; padding: 0.5rem; border-bottom: 1px solid #ecf0f1;">
                <label style="flex: 1; margin: 0; cursor: pointer;">
                    <input type="checkbox"
                           class="model-enable-checkbox"
                           data-model-name="${model.name}"
                           ${model.enabled ? 'checked' : ''}
                           onchange="toggleModelEnabled('${model.name}', this.checked)"
                           style="margin-right: 0.5rem; cursor: pointer;">
                    <strong>${model.display_name}</strong>
                    <span style="color: #7f8c8d; font-size: 0.85rem; margin-left: 0.5rem;">(${model.name})</span>
                </label>
                <span class="badge ${model.enabled ? 'badge-success' : 'badge-secondary'}" style="font-size: 0.75rem;">
                    ${model.enabled ? '有効 / Enabled' : '無効 / Disabled'}
                </span>
            </div>
        `).join('');
    } catch (error) {
        const container = document.getElementById('model-enable-settings');
        if (container) {
            container.innerHTML = '<p class="error">モデル設定の読み込みに失敗しました / Failed to load model settings</p>';
        }
    }
}

async function toggleModelEnabled(modelName, enabled) {
    try {
        const response = await fetch(`/api/settings/models/${modelName}/enable?enabled=${enabled}`, {
            method: 'PUT'
        });

        if (!response.ok) {
            throw new Error('Failed to update model status');
        }

        // Reload model lists
        await loadAvailableModels();

        // Show success message
        const message = enabled ?
            `${modelName} を有効化しました / Enabled ${modelName}` :
            `${modelName} を無効化しました / Disabled ${modelName}`;

        // Create temporary success message
        const container = document.getElementById('model-enable-settings');
        const successMsg = document.createElement('div');
        successMsg.className = 'success-message';
        successMsg.style.cssText = 'background: #27ae60; color: white; padding: 0.5rem; margin: 0.5rem 0; border-radius: 4px;';
        successMsg.textContent = message;
        container.insertBefore(successMsg, container.firstChild);

        setTimeout(() => successMsg.remove(), 3000);

    } catch (error) {
        alert(`エラー / Error: ${error.message}`);
        // Reload to reset checkbox state
        await loadModelEnableSettings();
    }
}

// ========== DATASETS TAB ==========

async function loadDatasets() {
    try {
        const response = await fetch('/api/datasets');
        allDatasets = await response.json();
        renderDatasets();
    } catch (error) {
        // Failed to load datasets - silently continue
    }
}

function renderDatasets() {
    const container = document.getElementById('datasets-list');
    if (!container) return;

    if (allDatasets.length === 0) {
        container.innerHTML = '<p class="info">データセットがありません / No datasets</p>';
        return;
    }

    container.innerHTML = allDatasets.map(dataset => `
        <div class="list-item">
            <div class="item-header">
                <div class="item-title">${dataset.name}</div>
                <div class="item-actions">
                    <button class="btn btn-secondary" onclick="previewDataset(${dataset.id})">プレビュー / Preview</button>
                    <button class="btn btn-secondary" onclick="deleteDataset(${dataset.id})">削除 / Delete</button>
                </div>
            </div>
            <div class="item-meta">
                ファイル: ${dataset.source_file_name} | 行数: ${dataset.row_count} | 作成日: ${new Date(dataset.created_at).toLocaleString('ja-JP')}
            </div>
        </div>
    `).join('');
}

function showImportDatasetModal() {
    showModal(`
        <div class="modal-header">データセットインポート / Import Dataset</div>
        <div class="modal-body">
            <div class="form-group">
                <label>プロジェクト / Project:</label>
                <select id="import-project-id">
                    ${allProjects.map(p => `<option value="${p.id}">${p.name}</option>`).join('')}
                </select>
            </div>
            <div class="form-group">
                <label>データセット名 / Dataset Name:</label>
                <input type="text" id="import-dataset-name" required>
            </div>
            <div class="form-group">
                <label>範囲名 / Range Name:</label>
                <input type="text" id="import-range-name" value="DSRange">
            </div>
            <div class="form-group">
                <label>Excelファイル / Excel File:</label>
                <input type="file" id="import-file" accept=".xlsx,.xls" required>
            </div>
        </div>
        <div class="modal-footer">
            <button class="btn btn-secondary" onclick="closeModal()">キャンセル / Cancel</button>
            <button class="btn btn-primary" onclick="importDataset()">インポート / Import</button>
        </div>
    `);
}

async function importDataset() {
    const projectId = document.getElementById('import-project-id').value;
    const name = document.getElementById('import-dataset-name').value;
    const rangeName = document.getElementById('import-range-name').value;
    const fileInput = document.getElementById('import-file');

    if (!name || !fileInput.files[0]) {
        alert('すべての項目を入力してください / Please fill all fields');
        return;
    }

    const formData = new FormData();
    formData.append('project_id', projectId);
    formData.append('dataset_name', name);
    formData.append('range_name', rangeName);
    formData.append('file', fileInput.files[0]);

    try {
        const response = await fetch('/api/datasets/import', {
            method: 'POST',
            body: formData
        });

        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.detail || 'Import failed');
        }

        closeModal();
        await loadDatasets();
        alert('データセットをインポートしました / Dataset imported');
    } catch (error) {
        alert(`エラー / Error: ${error.message}`);
    }
}

async function previewDataset(id) {
    try {
        const response = await fetch(`/api/datasets/${id}/preview`);
        const preview = await response.json();

        const rowsHtml = preview.rows.map(row => {
            const cells = preview.columns.map(col => `<td>${row[col] || ''}</td>`).join('');
            return `<tr>${cells}</tr>`;
        }).join('');

        showModal(`
            <div class="modal-header">データセットプレビュー / Dataset Preview: ${preview.name}</div>
            <div class="modal-body">
                <p>総行数 / Total Rows: ${preview.total_count}</p>
                <div style="overflow-x: auto;">
                    <table style="width: 100%; border-collapse: collapse;">
                        <thead>
                            <tr>${preview.columns.map(col => `<th style="border: 1px solid #ddd; padding: 8px;">${col}</th>`).join('')}</tr>
                        </thead>
                        <tbody>${rowsHtml}</tbody>
                    </table>
                </div>
            </div>
            <div class="modal-footer">
                <button class="btn btn-primary" onclick="closeModal()">閉じる / Close</button>
            </div>
        `);
    } catch (error) {
        alert(`エラー / Error: ${error.message}`);
    }
}

async function deleteDataset(id) {
    if (!confirm('このデータセットを削除しますか？ / Delete this dataset?')) return;

    try {
        const response = await fetch(`/api/datasets/${id}`, {method: 'DELETE'});
        if (!response.ok) throw new Error('Failed to delete dataset');

        await loadDatasets();
        alert('データセットを削除しました / Dataset deleted');
    } catch (error) {
        alert(`エラー / Error: ${error.message}`);
    }
}

// ========== MODAL UTILITIES ==========

function showModal(content) {
    const modal = document.getElementById('modal-overlay');
    const modalContent = document.getElementById('modal-content');
    if (modal && modalContent) {
        modalContent.innerHTML = content;
        modal.classList.add('show');
    }
}

function closeModal() {
    const modal = document.getElementById('modal-overlay');
    if (modal) {
        modal.classList.remove('show');
    }
}

function showParserHelp() {
    const helpContent = `
        <div class="modal-header">
            パーサー設定ヘルプ / Parser Configuration Help
        </div>
        <div class="modal-body" style="max-height: 70vh; overflow-y: auto;">
            <h3 style="color: #2c3e50; border-bottom: 2px solid #3498db; padding-bottom: 0.5rem;">📖 パーサー設定の概要 / Parser Configuration Overview</h3>
            <p style="margin: 1rem 0;">
                パーサーは、LLMからの生レスポンスを構造化されたデータに変換するための機能です。<br>
                特にCSV形式での出力を行う場合、パーサー設定が必須です。
            </p>
            <p style="margin: 1rem 0; font-style: italic; color: #7f8c8d;">
                The parser converts raw LLM responses into structured data.<br>
                Parser configuration is required for CSV output functionality.
            </p>

            <h3 style="color: #2c3e50; border-bottom: 2px solid #3498db; padding-bottom: 0.5rem; margin-top: 2rem;">🔧 パーサータイプ / Parser Types</h3>

            <h4 style="color: #27ae60; margin-top: 1rem;">1. JSON Path パーサー (推奨 / Recommended)</h4>
            <p><strong>用途:</strong> LLMがJSON形式でレスポンスを返す場合</p>
            <pre style="background: #f8f9fa; padding: 1rem; border-radius: 4px; overflow-x: auto;"><code>{
  "type": "json_path",
  "paths": {
    "answer": "$.answer",
    "confidence": "$.confidence",
    "category": "$.category"
  },
  "csv_template": "$answer$,$confidence$,$category$"
}</code></pre>
            <ul style="margin: 0.5rem 0 1rem 2rem;">
                <li><code>paths</code>: 抽出するフィールド名とJSONパス</li>
                <li><code>csv_template</code>: CSV行の形式（$フィールド名$で置換）</li>
            </ul>

            <h4 style="color: #27ae60; margin-top: 1rem;">2. Regex パーサー</h4>
            <p><strong>用途:</strong> LLMがテキスト形式でレスポンスを返す場合</p>
            <pre style="background: #f8f9fa; padding: 1rem; border-radius: 4px; overflow-x: auto;"><code>{
  "type": "regex",
  "patterns": {
    "answer": "Answer: (.+)",
    "score": "Score: (\\\\d+)"
  },
  "csv_template": "$answer$,$score$"
}</code></pre>
            <ul style="margin: 0.5rem 0 1rem 2rem;">
                <li><code>patterns</code>: 抽出するフィールド名と正規表現パターン</li>
                <li>正規表現のグループ ( ) でキャプチャした部分が値になります</li>
            </ul>

            <h3 style="color: #2c3e50; border-bottom: 2px solid #3498db; padding-bottom: 0.5rem; margin-top: 2rem;">📊 CSV出力設定 / CSV Output Configuration</h3>
            <p style="margin: 1rem 0;">
                <strong>csv_template</strong>を設定すると、バッチ実行時に全ての結果が自動的にCSV形式に結合されます。
            </p>
            <ul style="margin: 0.5rem 0 1rem 2rem;">
                <li><code>$フィールド名$</code>の形式でフィールドを参照</li>
                <li>カンマ区切りで複数フィールドを指定</li>
                <li>例: <code>"$name$,$age$,$city$"</code> → <code>John,30,Tokyo</code></li>
            </ul>
            <div style="background: #e8f8f5; border-left: 4px solid #27ae60; padding: 1rem; margin: 1rem 0;">
                <strong>💡 ヒント:</strong> バッチ実行時に「CSVヘッダを１行目のみに含める」にチェックを入れると、<br>
                1行目にフィールド名のヘッダーが自動的に追加されます。
            </div>

            <h3 style="color: #2c3e50; border-bottom: 2px solid #3498db; padding-bottom: 0.5rem; margin-top: 2rem;">🤖 LLMにパーサー構文を作成してもらう方法 / Using LLM to Generate Parser Config</h3>
            <p style="margin: 1rem 0;">プロンプトテンプレートに以下のような指示を追加すると、LLMが自動的にパース可能な形式で返答します：</p>

            <h4 style="color: #27ae60; margin-top: 1rem;">JSON形式の場合:</h4>
            <pre style="background: #f8f9fa; padding: 1rem; border-radius: 4px; overflow-x: auto;"><code>以下の質問に対して、必ず以下のJSON形式で回答してください：

{
  "answer": "あなたの回答",
  "confidence": "信頼度（0-1）",
  "category": "カテゴリ"
}

質問: {{question}}</code></pre>

            <h4 style="color: #27ae60; margin-top: 1rem;">テキスト形式の場合:</h4>
            <pre style="background: #f8f9fa; padding: 1rem; border-radius: 4px; overflow-x: auto;"><code>以下の質問に対して、必ず以下の形式で回答してください：

Answer: [あなたの回答]
Score: [スコア（0-100）]

質問: {{question}}</code></pre>

            <h3 style="color: #2c3e50; border-bottom: 2px solid #3498db; padding-bottom: 0.5rem; margin-top: 2rem;">✨ 完全な設定例 / Complete Configuration Example</h3>
            <pre style="background: #f8f9fa; padding: 1rem; border-radius: 4px; overflow-x: auto;"><code>{
  "type": "json_path",
  "paths": {
    "product_name": "$.product_name",
    "price": "$.price",
    "rating": "$.rating",
    "in_stock": "$.in_stock"
  },
  "csv_template": "$product_name$,$price$,$rating$,$in_stock$"
}</code></pre>
            <p style="margin: 1rem 0;">
                この設定により、バッチ実行で10件のデータを処理すると、<br>
                以下のような結合されたCSVが自動生成されます：
            </p>
            <pre style="background: #f8f9fa; padding: 1rem; border-radius: 4px; overflow-x: auto;"><code>product_name,price,rating,in_stock
Product A,1000,4.5,true
Product B,2000,4.2,false
...（全10行）</code></pre>

            <div style="background: #fff3cd; border-left: 4px solid #ffc107; padding: 1rem; margin: 1rem 0;">
                <strong>⚠️ 注意:</strong>
                <ul style="margin: 0.5rem 0 0 1rem;">
                    <li>フィールド名は<code>paths</code>と<code>csv_template</code>で一致させてください</li>
                    <li>JSON Pathは<code>$.</code>で始まります（例: <code>$.answer</code>）</li>
                    <li>CSV出力を使用する場合、<code>csv_template</code>は必須です</li>
                </ul>
            </div>
        </div>
        <div class="modal-footer">
            <button class="btn btn-primary" onclick="closeModal()">閉じる / Close</button>
        </div>
    `;
    showModal(helpContent);
}

// ========== SETTINGS MANAGEMENT ==========

let availableModelsData = [];
let currentModelParams = null;

async function loadSettings() {
    try {
        // Load available models
        const modelsResponse = await fetch('/api/settings/models/available');
        availableModelsData = await modelsResponse.json();

        // Populate all model selects
        populateModelSelects();

        // Load default model
        const defaultResponse = await fetch('/api/settings/models/default');
        const defaultData = await defaultResponse.json();
        document.getElementById('default-model-select').value = defaultData.default_model;

        // Set default model in execution dropdowns
        document.getElementById('model-select').value = defaultData.default_model;
        document.getElementById('batch-model-select').value = defaultData.default_model;

    } catch (error) {
        console.error('Failed to load settings:', error);
    }
}

function populateModelSelects() {
    const selects = [
        'model-select',
        'batch-model-select',
        'default-model-select',
        'param-model-select'
    ];

    selects.forEach(selectId => {
        const select = document.getElementById(selectId);
        if (select) {
            select.innerHTML = availableModelsData.map(m =>
                `<option value="${m.name}">${m.display_name}</option>`
            ).join('');
        }
    });

    // Display available models list in settings
    const availableModelsDiv = document.getElementById('available-models');
    if (availableModelsDiv) {
        availableModelsDiv.innerHTML = `
            <ul>
                ${availableModelsData.map(m => `<li>${m.display_name} (${m.name})</li>`).join('')}
            </ul>
        `;
    }

    // Auto-select first model in param-model-select and load its parameters
    const paramSelect = document.getElementById('param-model-select');
    if (paramSelect && availableModelsData.length > 0) {
        paramSelect.value = availableModelsData[0].name;
        // Trigger load parameters for the first model
        loadModelParameters();
    }
}

async function saveDefaultModel() {
    const modelName = document.getElementById('default-model-select').value;

    try {
        const response = await fetch(`/api/settings/models/default?model_name=${modelName}`, {
            method: 'PUT'
        });

        if (!response.ok) throw new Error('Failed to save default model');

        alert('デフォルトモデルを保存しました / Default model saved');

        // Update execution dropdowns
        document.getElementById('model-select').value = modelName;
        document.getElementById('batch-model-select').value = modelName;

    } catch (error) {
        alert(`エラー / Error: ${error.message}`);
    }
}

async function saveDefaultProject() {
    const projectId = document.getElementById('default-project-select').value;

    if (!projectId) {
        alert('プロジェクトを選択してください / Please select a project');
        return;
    }

    try {
        const response = await fetch(`/api/settings/default-project?project_id=${projectId}`, {
            method: 'PUT'
        });

        if (!response.ok) throw new Error('Failed to save default project');

        const data = await response.json();
        alert(`デフォルトプロジェクトを保存しました / Default project saved: ${data.project_name}`);

        // Update single execution dropdown
        const singleSelect = document.getElementById('single-project-select');
        if (singleSelect) {
            singleSelect.value = projectId;
            // Trigger project change to load prompts
            await onProjectChange();
        }

    } catch (error) {
        alert(`エラー / Error: ${error.message}`);
    }
}

async function loadModelParameters() {
    const modelName = document.getElementById('param-model-select').value;
    if (!modelName) return;

    try {
        const response = await fetch(`/api/settings/models/${modelName}/parameters`);
        currentModelParams = await response.json();

        // Show form
        document.getElementById('model-parameters-form').style.display = 'block';

        // Populate form with active parameters
        const active = currentModelParams.active_parameters;
        const defaults = currentModelParams.default_parameters;

        // Check if GPT-5 model
        const isGPT5 = modelName.includes('gpt-5') || modelName.includes('gpt5');

        // Get all parameter groups
        const temperatureGroup = document.getElementById('param-temperature-group');
        const maxTokensGroup = document.getElementById('param-max-tokens-group');
        const topPGroup = document.getElementById('param-top-p-group');
        const verbosityGroup = document.getElementById('param-verbosity-group');
        const reasoningEffortGroup = document.getElementById('param-reasoning-effort-group');

        if (isGPT5) {
            // GPT-5: Hide traditional parameters, show GPT-5 specific parameters
            temperatureGroup.style.display = 'none';
            maxTokensGroup.style.display = 'none';
            topPGroup.style.display = 'none';
            verbosityGroup.style.display = 'block';
            reasoningEffortGroup.style.display = 'block';

            // Set GPT-5 parameter values
            document.getElementById('param-verbosity').value = active.verbosity || defaults.verbosity || 'medium';
            document.getElementById('param-reasoning-effort').value = active.reasoning_effort || defaults.reasoning_effort || 'medium';

            document.getElementById('default-verbosity').textContent = `(デフォルト / Default: ${defaults.verbosity || 'medium'})`;
            document.getElementById('default-reasoning-effort').textContent = `(デフォルト / Default: ${defaults.reasoning_effort || 'medium'})`;
        } else {
            // Non-GPT-5: Show traditional parameters, hide GPT-5 specific parameters
            temperatureGroup.style.display = 'block';
            maxTokensGroup.style.display = 'block';
            topPGroup.style.display = 'block';
            verbosityGroup.style.display = 'none';
            reasoningEffortGroup.style.display = 'none';

            // Set traditional parameter values
            document.getElementById('param-temperature').value = active.temperature;
            document.getElementById('param-max-tokens').value = active.max_tokens;
            document.getElementById('param-top-p').value = active.top_p;

            document.getElementById('default-temperature').textContent = `(デフォルト / Default: ${defaults.temperature})`;
            document.getElementById('default-max-tokens').textContent = `(デフォルト / Default: ${defaults.max_tokens})`;
            document.getElementById('default-top-p').textContent = `(デフォルト / Default: ${defaults.top_p})`;
        }

    } catch (error) {
        alert(`エラー / Error: ${error.message}`);
    }
}

async function saveModelParameters() {
    const modelName = document.getElementById('param-model-select').value;
    const isGPT5 = modelName.includes('gpt-5') || modelName.includes('gpt5');

    let parameters;

    if (isGPT5) {
        // GPT-5: Only send GPT-5 specific parameters
        parameters = {
            verbosity: document.getElementById('param-verbosity').value,
            reasoning_effort: document.getElementById('param-reasoning-effort').value
        };
    } else {
        // Non-GPT-5: Send traditional parameters
        parameters = {
            temperature: parseFloat(document.getElementById('param-temperature').value),
            max_tokens: parseInt(document.getElementById('param-max-tokens').value),
            top_p: parseFloat(document.getElementById('param-top-p').value)
        };
    }

    try {
        const response = await fetch(`/api/settings/models/${modelName}/parameters`, {
            method: 'PUT',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({model_name: modelName, parameters})
        });

        if (!response.ok) throw new Error('Failed to save parameters');

        alert('パラメータを保存しました / Parameters saved');
        await loadModelParameters();

    } catch (error) {
        alert(`エラー / Error: ${error.message}`);
    }
}

async function resetModelParameters() {
    const modelName = document.getElementById('param-model-select').value;

    if (!confirm('パラメータをデフォルトに戻しますか？ / Reset parameters to defaults?')) return;

    try {
        const response = await fetch(`/api/settings/models/${modelName}/parameters`, {
            method: 'DELETE'
        });

        if (!response.ok) throw new Error('Failed to reset parameters');

        alert('パラメータをリセットしました / Parameters reset');
        await loadModelParameters();

    } catch (error) {
        alert(`エラー / Error: ${error.message}`);
    }
}

// ========================================
// Job Parallelism Settings
// ========================================

let currentSingleJobId = null;
let currentBatchJobId = null;

async function loadJobParallelism() {
    try {
        const response = await fetch('/api/settings/job-parallelism');
        if (!response.ok) throw new Error('Failed to load parallelism setting');

        const data = await response.json();
        document.getElementById('job-parallelism').value = data.parallelism;

    } catch (error) {
        console.error('Failed to load job parallelism:', error);
    }
}

async function saveJobParallelism() {
    const parallelism = parseInt(document.getElementById('job-parallelism').value);
    const statusEl = document.getElementById('parallelism-status');

    if (parallelism < 1 || parallelism > 99) {
        statusEl.textContent = 'エラー: 1-99の範囲で設定してください / Error: Must be 1-99';
        statusEl.style.color = '#e74c3c';
        return;
    }

    try {
        const response = await fetch(`/api/settings/job-parallelism?parallelism=${parallelism}`, {
            method: 'PUT'
        });

        if (!response.ok) throw new Error('Failed to save parallelism setting');

        const data = await response.json();
        statusEl.textContent = '保存しました / Saved';
        statusEl.style.color = '#27ae60';

        setTimeout(() => {
            statusEl.textContent = '';
        }, 2000);

    } catch (error) {
        statusEl.textContent = `エラー / Error: ${error.message}`;
        statusEl.style.color = '#e74c3c';
    }
}

// ========================================
// Job Cancellation
// ========================================

async function cancelJob(jobId, buttonId, statusId) {
    if (!jobId) {
        alert('ジョブが実行されていません / No job is running');
        return;
    }

    try {
        const response = await fetch(`/api/jobs/${jobId}/cancel`, {
            method: 'POST'
        });

        if (!response.ok) throw new Error('Failed to cancel job');

        const data = await response.json();

        // Hide stop button
        document.getElementById(buttonId).style.display = 'none';

        // Show status message
        const statusEl = document.getElementById(statusId);
        if (statusEl) {
            statusEl.textContent = `停止しました: ${data.cancelled_count}件のアイテムをキャンセル / Stopped: ${data.cancelled_count} items cancelled`;
            statusEl.className = 'status-message status-info';
        }

    } catch (error) {
        alert(`停止エラー / Cancellation Error: ${error.message}`);
    }
}

async function cancelSingleJob() {
    // Stop polling first
    if (singlePollIntervalId) {
        clearInterval(singlePollIntervalId);
        singlePollIntervalId = null;
    }

    const jobId = currentSingleJobId;
    await cancelJob(currentSingleJobId, 'btn-stop-single', 'execution-status');
    hideSingleStopButton();

    // Reload job state and history after cancellation
    if (jobId && currentProjectId) {
        try {
            // Fetch updated job data
            const response = await fetch(`/api/projects/${currentProjectId}/jobs`);
            const allJobs = await response.json();
            const job = allJobs.find(j => j.id === jobId);

            if (job) {
                // Display final job state
                displayJobResults(job);
            }

            // Reload history
            await loadConfig();
        } catch (error) {
            console.error('Error reloading job after cancel:', error);
        }
    }
}

async function cancelBatchJob() {
    // Stop polling first
    if (batchPollIntervalId) {
        clearInterval(batchPollIntervalId);
        batchPollIntervalId = null;
    }

    const jobId = currentBatchJobId;
    const projectId = document.getElementById('batch-project-select')?.value;

    await cancelJob(currentBatchJobId, 'btn-stop-batch', 'batch-results-area');
    hideBatchStopButton();

    // Reload job state and history after cancellation
    if (jobId && projectId) {
        try {
            // Fetch updated job data
            const response = await fetch(`/api/projects/${projectId}/jobs`);
            const allJobs = await response.json();
            const job = allJobs.find(j => j.id === parseInt(jobId));

            if (job) {
                // Display final job state
                displayBatchResult(job);
            }

            // Reload batch job history
            await loadBatchJobHistory(parseInt(projectId));
        } catch (error) {
            console.error('Error reloading job after cancel:', error);
        }
    }
}
