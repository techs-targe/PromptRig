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

// Single execution history pagination
let singleHistoryOffset = 0;
const SINGLE_HISTORY_PAGE_SIZE = 10;
let singleHistoryHasMore = true;

/**
 * Format date to JST (Japan Standard Time)
 * Database timestamps are stored in UTC without timezone suffix.
 * This function interprets them as UTC and converts to JST for display.
 *
 * @param {string|Date} dateInput - Date string or Date object (stored in UTC)
 * @param {boolean} includeSeconds - Whether to include seconds (default: false)
 * @returns {string} Formatted date string in JST (YYYY/MM/DD HH:MM)
 */
function formatJST(dateInput, includeSeconds = false) {
    if (!dateInput) return '-';
    try {
        let date;

        if (dateInput instanceof Date) {
            date = dateInput;
        } else {
            // Convert input to string
            let dateStr = String(dateInput);

            // Database timestamps are UTC but stored without 'Z' suffix
            // Append 'Z' to mark as UTC if no timezone info present
            // This ensures proper UTC -> JST conversion (+9 hours)
            if (!dateStr.endsWith('Z') && !dateStr.includes('+') && !dateStr.includes('-', 10)) {
                // Replace space with 'T' for ISO format if needed
                dateStr = dateStr.replace(' ', 'T');
                dateStr = dateStr + 'Z';
            }

            date = new Date(dateStr);
        }

        if (isNaN(date.getTime())) return '-';

        // Format in JST timezone (UTC+9)
        const options = {
            timeZone: 'Asia/Tokyo',
            year: 'numeric',
            month: '2-digit',
            day: '2-digit',
            hour: '2-digit',
            minute: '2-digit',
            hour12: false
        };

        if (includeSeconds) {
            options.second = '2-digit';
        }

        return date.toLocaleString('ja-JP', options);
    } catch (e) {
        return '-';
    }
}

// Global storage for CSV content (to avoid escaping issues in onclick)
const csvStorage = {};

/**
 * Store CSV content for a job
 * @param {number} jobId - The job ID
 * @param {string} csvContent - The CSV content
 */
function storeCsvContent(jobId, csvContent) {
    csvStorage[jobId] = csvContent;
}

/**
 * Copy CSV content to clipboard
 * @param {number} jobId - The job ID
 */
function copyCsvToClipboard(jobId) {
    const content = csvStorage[jobId];
    if (!content) {
        alert('CSVデータが見つかりません / CSV data not found');
        return;
    }
    navigator.clipboard.writeText(content).then(() => {
        alert('統合CSVをクリップボードにコピーしました / Merged CSV copied to clipboard');
    }).catch(err => {
        alert('コピーに失敗しました / Copy failed: ' + err.message);
    });
}

/**
 * Download CSV content as a file
 * @param {number} jobId - The job ID
 * @param {string} filename - The filename for download
 */
function downloadCsvByJobId(jobId, filename) {
    const content = csvStorage[jobId];
    if (!content) {
        alert('CSVデータが見つかりません / CSV data not found');
        return;
    }
    try {
        // Add BOM for Excel compatibility with Japanese characters
        const bom = '\uFEFF';
        const blob = new Blob([bom + content], { type: 'text/csv;charset=utf-8;' });

        // Create download link
        const link = document.createElement('a');
        const url = URL.createObjectURL(blob);
        link.setAttribute('href', url);
        link.setAttribute('download', filename);
        link.style.visibility = 'hidden';
        document.body.appendChild(link);
        link.click();
        document.body.removeChild(link);
        URL.revokeObjectURL(url);
    } catch (e) {
        alert('ダウンロードに失敗しました / Download failed: ' + e.message);
    }
}

/**
 * Legacy download function for backward compatibility
 * @param {string} csvContent - The CSV content (escaped with \n for newlines)
 * @param {string} filename - The filename for download
 */
function downloadCsv(csvContent, filename) {
    try {
        // Unescape newlines and single quotes
        const unescapedContent = csvContent.replace(/\\n/g, '\n').replace(/\\'/g, "'");

        // Add BOM for Excel compatibility with Japanese characters
        const bom = '\uFEFF';
        const blob = new Blob([bom + unescapedContent], { type: 'text/csv;charset=utf-8;' });

        // Create download link
        const link = document.createElement('a');
        const url = URL.createObjectURL(blob);
        link.setAttribute('href', url);
        link.setAttribute('download', filename);
        link.style.visibility = 'hidden';
        document.body.appendChild(link);
        link.click();
        document.body.removeChild(link);
        URL.revokeObjectURL(url);
    } catch (e) {
        alert('ダウンロードに失敗しました / Download failed: ' + e.message);
    }
}

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
        // Load projects first (this also sets default project and loads config)
        await loadProjects();

        // Load settings and models
        await loadSettings();

        // Load datasets
        await loadDatasets();

        // Load available models
        await loadAvailableModels();

        // Note: loadConfig() is now called from updateProjectSelects() after setting the default project
        // This ensures currentProjectId matches the selected dropdown value
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
            loadModelConfigurationSettings();
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

        // Reset pagination state
        singleHistoryOffset = 0;
        singleHistoryHasMore = true;

        // Get project details
        const projectResponse = await fetch(`/api/projects/${pid}`);
        if (!projectResponse.ok) throw new Error(`Failed to load project ${pid}`);
        const project = await projectResponse.json();

        // Get jobs for this project with pagination
        const jobsResponse = await fetch(`/api/projects/${pid}/jobs?limit=${SINGLE_HISTORY_PAGE_SIZE}&offset=0`);
        if (!jobsResponse.ok) throw new Error(`Failed to load jobs for project ${pid}`);
        const allJobs = await jobsResponse.json();

        // Check if we got fewer items than requested
        if (allJobs.length < SINGLE_HISTORY_PAGE_SIZE) {
            singleHistoryHasMore = false;
        }

        // Filter single-type jobs
        const singleJobs = allJobs.filter(job => job.job_type === 'single');

        // Use parameters from API (parsed by backend)
        const parameters = project.parameters || [];

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

        // Add required asterisk if parameter is required
        if (param.required) {
            label.innerHTML = `${param.name} (${param.type}) <span class="required-asterisk">*</span>`;
        } else {
            label.textContent = `${param.name} (${param.type})`;
        }

        let input;
        if (param.html_type === 'textarea') {
            input = document.createElement('textarea');
            input.rows = param.rows || 5;  // Default to 5 rows
            input.id = `param-${param.name}`;
            input.name = param.name;
            input.required = param.required;

            // Set default value if provided
            if (param.default) {
                input.value = param.default;
            }

            group.appendChild(label);
            group.appendChild(input);
            container.appendChild(group);
            return; // Skip the default input append
        } else if (param.html_type === 'file') {
            // Enhanced FILE input with preview, info, and reset button
            input = document.createElement('input');
            input.type = 'file';
            input.id = `param-${param.name}`;
            input.name = param.name;
            input.required = param.required;

            if (param.accept) {
                input.accept = param.accept;
            }

            // Create wrapper for file input with drag & drop support
            const fileWrapper = document.createElement('div');
            fileWrapper.className = 'file-input-wrapper';
            fileWrapper.innerHTML = `
                <div class="file-drop-zone" id="drop-zone-${param.name}">
                    <div class="file-drop-icon">📁</div>
                    <div class="file-drop-text">クリックまたはドラッグ&ドロップ<br>Click or drag & drop image here</div>
                </div>
                <div class="file-info-container" id="file-info-${param.name}" style="display: none;">
                    <div class="file-info-header">
                        <span class="file-info-name" id="file-name-${param.name}"></span>
                        <button type="button" class="btn-file-clear" id="clear-${param.name}">✕ クリア</button>
                    </div>
                    <div class="file-info-details">
                        <span class="file-info-size" id="file-size-${param.name}"></span>
                        <span class="file-info-type" id="file-type-${param.name}"></span>
                    </div>
                </div>
                <div class="image-preview-container" id="preview-container-${param.name}" style="display: none;">
                    <img class="image-preview" id="preview-${param.name}" alt="Preview">
                </div>
            `;

            // Insert hidden file input
            fileWrapper.insertBefore(input, fileWrapper.firstChild);

            group.appendChild(label);
            group.appendChild(fileWrapper);
            container.appendChild(group);

            // Setup file input handlers after DOM insertion
            setupFileInputHandlers(param.name);
            return; // Skip the default input append
        } else if (param.type === 'FILEPATH') {
            // FILEPATH: Text input with file picker button
            const filepathWrapper = document.createElement('div');
            filepathWrapper.className = 'filepath-input-wrapper';

            // Hidden file input for triggering file picker
            const hiddenFileInput = document.createElement('input');
            hiddenFileInput.type = 'file';
            hiddenFileInput.id = `filepath-picker-${param.name}`;
            hiddenFileInput.style.display = 'none';
            hiddenFileInput.accept = 'image/*,.pdf,.xlsx,.xls,.csv,.txt,.json';

            // Text input for path display
            input = document.createElement('input');
            input.type = 'text';
            input.id = `param-${param.name}`;
            input.name = param.name;
            input.required = param.required;
            input.placeholder = param.placeholder || '/path/to/file';
            input.className = 'filepath-text-input';
            if (param.default) {
                input.value = param.default;
            }

            // Browse button
            const browseBtn = document.createElement('button');
            browseBtn.type = 'button';
            browseBtn.className = 'btn btn-secondary filepath-browse-btn';
            browseBtn.textContent = '参照...';
            browseBtn.title = 'ファイルを選択してアップロード / Select file to upload';

            // Click handler for browse button
            browseBtn.addEventListener('click', () => {
                hiddenFileInput.click();
            });

            // File selection handler
            hiddenFileInput.addEventListener('change', async (e) => {
                const file = e.target.files[0];
                if (!file) return;

                // Show uploading state
                browseBtn.disabled = true;
                browseBtn.textContent = 'アップロード中...';
                input.value = 'アップロード中... / Uploading...';

                try {
                    const formData = new FormData();
                    formData.append('file', file);

                    const response = await fetch('/api/upload/filepath', {
                        method: 'POST',
                        body: formData
                    });

                    if (!response.ok) {
                        throw new Error('Upload failed');
                    }

                    const result = await response.json();
                    input.value = result.path;
                    input.title = `Original: ${result.filename}`;
                } catch (error) {
                    console.error('File upload failed:', error);
                    input.value = '';
                    alert('ファイルのアップロードに失敗しました / File upload failed');
                } finally {
                    browseBtn.disabled = false;
                    browseBtn.textContent = '参照...';
                    hiddenFileInput.value = ''; // Reset for next selection
                }
            });

            filepathWrapper.appendChild(hiddenFileInput);
            filepathWrapper.appendChild(input);
            filepathWrapper.appendChild(browseBtn);

            group.appendChild(label);
            group.appendChild(filepathWrapper);
            container.appendChild(group);
            return; // Skip the default input append
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

            // Set default value if provided
            if (param.default) {
                input.value = param.default;
            }
        }

        input.id = `param-${param.name}`;
        input.name = param.name;
        input.required = param.required;

        group.appendChild(label);
        group.appendChild(input);
        container.appendChild(group);
    });
}

function renderHistory(jobs, append = false) {
    const container = document.getElementById('history-list');
    if (!container) return;

    // Update recent_jobs when appending
    if (append && currentConfig) {
        currentConfig.recent_jobs = [...currentConfig.recent_jobs, ...(jobs || [])];
    }

    const allJobs = currentConfig?.recent_jobs || jobs || [];

    if (!allJobs || allJobs.length === 0) {
        container.innerHTML = '<p class="info">履歴がありません / No history</p>';
        return;
    }

    const jobsToRender = append ? jobs : allJobs;

    const jobsHtml = jobsToRender.map(job => {
        const createdAt = formatJST(job.created_at);
        const finishedAt = formatJST(job.finished_at);
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

    if (append) {
        // Remove existing load-more link first
        const existingLoadMore = container.querySelector('.load-more-link');
        if (existingLoadMore) existingLoadMore.remove();
        // Append new jobs
        container.insertAdjacentHTML('beforeend', jobsHtml);
    } else {
        container.innerHTML = jobsHtml;
    }

    // Add "Load more" link if there might be more jobs
    if (singleHistoryHasMore) {
        const loadMoreHtml = `
            <div class="load-more-link" onclick="loadMoreSingleHistory()">
                <span>さらに表示... / Load more...</span>
            </div>
        `;
        container.insertAdjacentHTML('beforeend', loadMoreHtml);
    }
}

async function loadMoreSingleHistory() {
    if (!currentConfig) return;
    const projectId = currentConfig.project_id;

    singleHistoryOffset += SINGLE_HISTORY_PAGE_SIZE;

    try {
        const response = await fetch(`/api/projects/${projectId}/jobs?limit=${SINGLE_HISTORY_PAGE_SIZE}&offset=${singleHistoryOffset}`);
        const allJobs = await response.json();
        const singleJobs = allJobs.filter(job => job.job_type === 'single');

        // Check if we got fewer items than requested (no more to load)
        if (allJobs.length < SINGLE_HISTORY_PAGE_SIZE) {
            singleHistoryHasMore = false;
        }

        renderHistory(singleJobs, true);
    } catch (error) {
        console.error('Failed to load more single history:', error);
    }
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
        // Store CSV content in global storage to avoid escaping issues
        storeCsvContent(job.id, job.merged_csv_output);
        const isBatch = job.job_type === 'batch';
        const title = isBatch ? 'バッチ実行結果 (CSV統合) / Batch Results (Merged CSV)' : 'n回送信結果 (CSV統合) / Repeated Execution Results (Merged CSV)';
        const csvFilename = `job_${job.id}_results_${new Date().toISOString().slice(0,10)}.csv`;
        // Escape HTML entities for display in <pre> tag
        const displayCsv = escapeHtml(job.merged_csv_output);
        mergedCsvSection = `
            <div class="result-item" style="background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; border-left: 5px solid #f39c12;">
                <div class="item-header" style="color: white; font-size: 1.2rem;">
                    📊 ${title}
                </div>
                <div style="margin-top: 1rem; background: white; color: #2c3e50; padding: 1rem; border-radius: 4px;">
                    <div class="response-box" style="background-color: #f8f9fa; font-family: 'Courier New', monospace; max-height: 400px; overflow-y: auto;">
                        <pre style="white-space: pre-wrap; word-wrap: break-word;">${displayCsv}</pre>
                    </div>
                    <div style="margin-top: 1rem; display: flex; gap: 0.5rem; flex-wrap: wrap;">
                        <button onclick="copyCsvToClipboard(${job.id})"
                                style="padding: 0.5rem 1.5rem; background: #27ae60; color: white; border: none; border-radius: 4px; cursor: pointer; font-weight: bold;">
                            📋 統合CSVをコピー / Copy Merged CSV
                        </button>
                        <button onclick="downloadCsvByJobId(${job.id}, 'job_${job.id}_results_${new Date().toISOString().slice(0,10)}.csv')"
                                style="padding: 0.5rem 1.5rem; background: #3498db; color: white; border: none; border-radius: 4px; cursor: pointer; font-weight: bold;">
                            💾 CSVをダウンロード / Download CSV
                        </button>
                    </div>
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
                            // Store item CSV in global storage with unique key
                            const itemCsvKey = `item_${job.id}_${index}`;
                            storeCsvContent(itemCsvKey, parsed.csv_output);
                            parsedContent = `
                                <div style="margin-top: 1rem;">
                                    <h4 style="color: #27ae60; margin-bottom: 0.5rem;">📊 パーサー結果 (CSV形式) / Parsed Results (CSV):</h4>
                                    <div class="response-box" style="background-color: #e8f8f5; font-family: 'Courier New', monospace;">
                                        <pre style="white-space: pre-wrap; word-wrap: break-word;">${escapeHtml(parsed.csv_output)}</pre>
                                    </div>
                                    <button onclick="copyCsvToClipboard('${itemCsvKey}')"
                                            style="margin-top: 0.5rem; padding: 0.5rem 1rem; background: #27ae60; color: white; border: none; border-radius: 4px; cursor: pointer;">
                                        📋 CSVをコピー / Copy CSV
                                    </button>
                                    <details style="margin-top: 0.5rem;">
                                        <summary style="cursor: pointer; color: #7f8c8d;">フィールド詳細を表示 / Show Field Details</summary>
                                        <pre style="margin-top: 0.5rem;">${escapeHtml(JSON.stringify(parsed.fields || {}, null, 2))}</pre>
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
        // Skip file inputs - cannot programmatically set file input values for security reasons
        if (input && input.type !== 'file') {
            input.value = value;
        }
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
                console.log(`📁 FILE parameter "${param.name}": ${file.name}, size: ${file.size} bytes`);
                const base64 = await fileToBase64(file);
                console.log(`📦 Base64 encoded length: ${base64.length} chars`);
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

        const requestBody = {
            project_id: currentProjectId || 1,
            input_params: inputParams,
            repeat: repeat,
            model_name: modelName,
            include_csv_header: includeCsvHeader,
            ...modelParams  // Include all model parameters from system settings
        };

        console.log('🚀 Sending request to /api/run/single');
        console.log('📊 Request body size:', JSON.stringify(requestBody).length, 'chars');

        const response = await fetch('/api/run/single', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify(requestBody)
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

/**
 * Setup event handlers for FILE type input
 * @param {string} paramName - Parameter name for the FILE input
 */
function setupFileInputHandlers(paramName) {
    const fileInput = document.getElementById(`param-${paramName}`);
    const dropZone = document.getElementById(`drop-zone-${paramName}`);
    const fileInfo = document.getElementById(`file-info-${paramName}`);
    const previewContainer = document.getElementById(`preview-container-${paramName}`);
    const preview = document.getElementById(`preview-${paramName}`);
    const fileName = document.getElementById(`file-name-${paramName}`);
    const fileSize = document.getElementById(`file-size-${paramName}`);
    const fileType = document.getElementById(`file-type-${paramName}`);
    const clearBtn = document.getElementById(`clear-${paramName}`);

    if (!fileInput || !dropZone) return;

    // Click on drop zone opens file picker
    dropZone.addEventListener('click', () => {
        fileInput.click();
    });

    // Handle file selection
    fileInput.addEventListener('change', (e) => {
        const file = e.target.files[0];
        if (file) {
            handleFileSelect(file);
        }
    });

    // Drag & drop handlers
    dropZone.addEventListener('dragover', (e) => {
        e.preventDefault();
        e.stopPropagation();
        dropZone.classList.add('dragover');
    });

    dropZone.addEventListener('dragleave', (e) => {
        e.preventDefault();
        e.stopPropagation();
        dropZone.classList.remove('dragover');
    });

    dropZone.addEventListener('drop', (e) => {
        e.preventDefault();
        e.stopPropagation();
        dropZone.classList.remove('dragover');

        const files = e.dataTransfer.files;
        if (files.length > 0) {
            fileInput.files = files;  // Update file input
            handleFileSelect(files[0]);
        }
    });

    // Clear button handler
    if (clearBtn) {
        clearBtn.addEventListener('click', (e) => {
            e.stopPropagation();  // Don't trigger drop zone click
            clearFileInput();
        });
    }

    function handleFileSelect(file) {
        // Validate file type
        const validTypes = ['image/jpeg', 'image/png', 'image/gif', 'image/webp'];
        if (!validTypes.includes(file.type)) {
            alert(`無効なファイル形式です / Invalid file type: ${file.type}\nサポート形式 / Supported: JPEG, PNG, GIF, WebP`);
            clearFileInput();
            return;
        }

        // Validate file size (20MB max)
        const maxSize = 20 * 1024 * 1024;  // 20MB
        if (file.size > maxSize) {
            alert(`ファイルサイズが大きすぎます / File too large: ${(file.size / 1024 / 1024).toFixed(2)}MB\n最大サイズ / Max size: 20MB`);
            clearFileInput();
            return;
        }

        // Show file info
        if (fileName) fileName.textContent = file.name;
        if (fileSize) fileSize.textContent = formatFileSize(file.size);
        if (fileType) fileType.textContent = file.type.split('/')[1].toUpperCase();

        // Hide drop zone, show file info
        if (dropZone) dropZone.style.display = 'none';
        if (fileInfo) fileInfo.style.display = 'block';

        // Load and show preview for images
        const reader = new FileReader();
        reader.onload = (e) => {
            if (preview) {
                preview.src = e.target.result;
                if (previewContainer) previewContainer.style.display = 'block';
            }
        };
        reader.readAsDataURL(file);
    }

    function clearFileInput() {
        // Clear file input
        fileInput.value = '';

        // Reset UI
        if (dropZone) dropZone.style.display = 'flex';
        if (fileInfo) fileInfo.style.display = 'none';
        if (previewContainer) previewContainer.style.display = 'none';
        if (preview) preview.src = '';
    }

    function formatFileSize(bytes) {
        if (bytes < 1024) return bytes + ' B';
        if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB';
        return (bytes / 1024 / 1024).toFixed(2) + ' MB';
    }
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
        // Fetch project and revisions in parallel
        const [projectResponse, revisionsResponse] = await Promise.all([
            fetch(`/api/projects/${currentProjectId}`),
            fetch(`/api/projects/${currentProjectId}/revisions`)
        ]);

        if (!projectResponse.ok) throw new Error('Failed to load project');
        const project = await projectResponse.json();
        const revisions = revisionsResponse.ok ? await revisionsResponse.json() : [];

        // Build revision selector options
        const revisionOptions = revisions.map(rev => {
            const date = formatJST(rev.created_at);
            const isCurrent = rev.revision === project.revision_count;
            return `<option value="${rev.revision}" ${isCurrent ? 'selected' : ''}>
                Rev.${rev.revision} (${date})${isCurrent ? ' - 現在' : ''}
            </option>`;
        }).join('');

        const modalContent = `
            <div class="modal-header">
                プロンプトテンプレート編集 / Edit Prompt Template
                <button onclick="showPromptTemplateHelp()" style="background: none; border: none; cursor: pointer; font-size: 1.2rem; margin-left: 10px;" title="ヘルプを表示 / Show Help">❓</button>
            </div>
            <div class="modal-body">
                <div class="form-group">
                    <label>プロジェクト / Project: ${project.name}</label>
                </div>
                <div class="form-group" style="display: flex; align-items: center; gap: 10px;">
                    <label style="margin: 0;">リビジョン / Revision:</label>
                    <select id="revision-selector" onchange="loadRevisionContent(this.value, 'prompt')" style="flex: 1;">
                        ${revisionOptions}
                    </select>
                    <button class="btn btn-secondary" onclick="restoreRevision('prompt')" style="background-color: #e67e22;" title="選択したリビジョンを復元 / Restore selected revision">
                        🔄 復元 / Restore
                    </button>
                </div>
                <div class="form-group">
                    <label>プロンプトテンプレート / Prompt Template:</label>
                    <textarea id="edit-prompt-template" rows="15" style="font-family: 'Courier New', monospace; width: 100%; box-sizing: border-box;">${project.prompt_template}</textarea>
                </div>
            </div>
            <div class="modal-footer">
                <button class="btn btn-secondary" onclick="closeModal()">キャンセル / Cancel</button>
                <button class="btn btn-primary" onclick="savePromptRevision()">保存 / Save</button>
            </div>
        `;
        showModal(modalContent);
    } catch (error) {
        alert(`エラー / Error: ${error.message}`);
    }
}

/**
 * Save (update) current prompt revision
 * Smart save: Creates new revision only if content changed
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

        if (!response.ok) throw new Error('Failed to save revision');

        const result = await response.json();
        closeModal();
        await loadConfig();

        if (result.is_new) {
            alert(`新しいリビジョン ${result.revision} を作成しました / New revision ${result.revision} created`);
        } else {
            alert('変更がありませんでした / No changes detected');
        }
    } catch (error) {
        alert(`エラー / Error: ${error.message}`);
    }
}

/**
 * Load revision content into the editor
 * @param {number} revisionNumber - The revision number to load
 * @param {string} type - 'prompt' or 'parser'
 */
async function loadRevisionContent(revisionNumber, type) {
    try {
        const response = await fetch(`/api/projects/${currentProjectId}/revisions`);
        if (!response.ok) throw new Error('Failed to load revisions');

        const revisions = await response.json();
        const revision = revisions.find(r => r.revision === parseInt(revisionNumber));

        if (!revision) {
            alert('リビジョンが見つかりません / Revision not found');
            return;
        }

        if (type === 'prompt') {
            document.getElementById('edit-prompt-template').value = revision.prompt_template;
        } else if (type === 'parser') {
            const parserConfig = revision.parser_config ? JSON.parse(revision.parser_config) : {type: 'none'};
            document.getElementById('edit-parser-type').value = parserConfig.type || 'none';
            document.getElementById('edit-parser-config').value = JSON.stringify(parserConfig, null, 2);
        }
    } catch (error) {
        alert(`エラー / Error: ${error.message}`);
    }
}

/**
 * Restore a past revision (creates new revision with old content)
 * @param {string} type - 'prompt' or 'parser' (for context, restore applies to both)
 */
async function restoreRevision(type) {
    const selector = document.getElementById('revision-selector');
    if (!selector) {
        alert('リビジョンセレクタが見つかりません / Revision selector not found');
        return;
    }

    const revisionNumber = parseInt(selector.value);
    const selectedOption = selector.options[selector.selectedIndex];
    const isCurrent = selectedOption.text.includes('現在');

    if (isCurrent) {
        alert('現在のリビジョンは復元できません（既に最新です）\nCannot restore current revision (already latest)');
        return;
    }

    if (!confirm(`リビジョン ${revisionNumber} を復元しますか？\n新しいリビジョンとして作成されます。\n\nRestore revision ${revisionNumber}?\nThis will create a new revision.`)) {
        return;
    }

    try {
        const response = await fetch(`/api/projects/${currentProjectId}/revisions/${revisionNumber}/restore`, {
            method: 'POST'
        });

        if (!response.ok) throw new Error('Failed to restore revision');

        const result = await response.json();
        closeModal();
        await loadConfig();
        alert(`リビジョン ${revisionNumber} を復元しました（新リビジョン: ${result.revision}）\nRestored revision ${revisionNumber} (new revision: ${result.revision})`);
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
        // Fetch project and revisions in parallel
        const [projectResponse, revisionsResponse] = await Promise.all([
            fetch(`/api/projects/${currentProjectId}`),
            fetch(`/api/projects/${currentProjectId}/revisions`)
        ]);

        if (!projectResponse.ok) throw new Error('Failed to load project');
        const project = await projectResponse.json();
        const revisions = revisionsResponse.ok ? await revisionsResponse.json() : [];

        const parserConfig = project.parser_config || {type: 'none'};
        const parserJson = JSON.stringify(parserConfig, null, 2);

        // Build revision selector options
        const revisionOptions = revisions.map(rev => {
            const date = formatJST(rev.created_at);
            const isCurrent = rev.revision === project.revision_count;
            return `<option value="${rev.revision}" ${isCurrent ? 'selected' : ''}>
                Rev.${rev.revision} (${date})${isCurrent ? ' - 現在' : ''}
            </option>`;
        }).join('');

        const modalContent = `
            <div class="modal-header">
                パーサー設定編集 / Edit Parser Configuration
                <button onclick="showParserHelp()" style="background: none; border: none; cursor: pointer; font-size: 1.2rem; margin-left: 10px;" title="ヘルプを表示 / Show Help">❓</button>
            </div>
            <div class="modal-body">
                <div class="form-group">
                    <label>プロジェクト / Project: ${project.name}</label>
                </div>
                <div class="form-group" style="display: flex; align-items: center; gap: 10px;">
                    <label style="margin: 0;">リビジョン / Revision:</label>
                    <select id="revision-selector" onchange="loadRevisionContent(this.value, 'parser')" style="flex: 1;">
                        ${revisionOptions}
                    </select>
                    <button class="btn btn-secondary" onclick="restoreRevision('parser')" style="background-color: #e67e22;" title="選択したリビジョンを復元 / Restore selected revision">
                        🔄 復元 / Restore
                    </button>
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
            <div class="modal-footer" style="display: flex; justify-content: space-between; flex-wrap: wrap; gap: 0.5rem;">
                <button class="btn" onclick="showJsonToCsvConverter()" style="background-color: #9b59b6;">📊 結果からCSVに変換 / Convert JSON to CSV</button>
                <div style="display: flex; gap: 0.5rem;">
                    <button class="btn btn-secondary" onclick="closeModal()">キャンセル / Cancel</button>
                    <button class="btn btn-primary" onclick="saveParserRevision()">保存 / Save</button>
                </div>
            </div>
        `;
        showModal(modalContent);
    } catch (error) {
        alert(`エラー / Error: ${error.message}`);
    }
}

/**
 * Save (update) current parser revision
 * Smart save: Creates new revision only if content changed
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

        if (!response.ok) throw new Error('Failed to save revision');

        const result = await response.json();
        closeModal();
        await loadConfig();

        if (result.is_new) {
            alert(`新しいリビジョン ${result.revision} を作成しました / New revision ${result.revision} created`);
        } else {
            alert('変更がありませんでした / No changes detected');
        }
    } catch (error) {
        alert(`エラー / Error: ${error.message}`);
    }
}

// ========== BATCH EXECUTION EDIT MODALS ==========

/**
 * Show batch edit prompt modal
 * Enhanced with revision selector and restore button (same as single execution)
 */
async function showBatchEditPromptModal() {
    const projectId = document.getElementById('batch-project-select').value;
    if (!projectId) {
        alert('プロジェクトを選択してください / Please select a project');
        return;
    }

    try {
        // Fetch project and revisions in parallel
        const [projectResponse, revisionsResponse] = await Promise.all([
            fetch(`/api/projects/${projectId}`),
            fetch(`/api/projects/${projectId}/revisions`)
        ]);

        if (!projectResponse.ok) throw new Error('Failed to load project');
        const project = await projectResponse.json();
        const revisions = revisionsResponse.ok ? await revisionsResponse.json() : [];

        // Build revision selector options
        const revisionOptions = revisions.map(rev => {
            const date = formatJST(rev.created_at);
            const isCurrent = rev.revision === project.revision_count;
            return `<option value="${rev.revision}" ${isCurrent ? 'selected' : ''}>
                Rev.${rev.revision} (${date})${isCurrent ? ' - 現在' : ''}
            </option>`;
        }).join('');

        const modalContent = `
            <div class="modal-header">
                プロンプトテンプレート編集 / Edit Prompt Template
                <button onclick="showPromptTemplateHelp()" style="background: none; border: none; cursor: pointer; font-size: 1.2rem; margin-left: 10px;" title="ヘルプを表示 / Show Help">❓</button>
            </div>
            <div class="modal-body">
                <div class="form-group">
                    <label>プロジェクト / Project: ${project.name}</label>
                </div>
                <div class="form-group" style="display: flex; align-items: center; gap: 10px;">
                    <label style="margin: 0;">リビジョン / Revision:</label>
                    <select id="batch-revision-selector" onchange="loadBatchRevisionContent(this.value, 'prompt', ${projectId})" style="flex: 1;">
                        ${revisionOptions}
                    </select>
                    <button class="btn btn-secondary" onclick="restoreBatchRevision('prompt', ${projectId})" style="background-color: #e67e22;" title="選択したリビジョンを復元 / Restore selected revision">
                        🔄 復元 / Restore
                    </button>
                </div>
                <div class="form-group">
                    <label>プロンプトテンプレート / Prompt Template:</label>
                    <textarea id="edit-prompt-template" rows="15" style="font-family: 'Courier New', monospace; width: 100%; box-sizing: border-box;">${project.prompt_template}</textarea>
                </div>
            </div>
            <div class="modal-footer">
                <button class="btn btn-secondary" onclick="closeModal()">キャンセル / Cancel</button>
                <button class="btn btn-primary" onclick="saveBatchPromptRevision(${projectId})">保存 / Save</button>
            </div>
        `;
        showModal(modalContent);
    } catch (error) {
        alert(`エラー / Error: ${error.message}`);
    }
}

/**
 * Save batch prompt revision
 * Smart save: Creates new revision only if content changed
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

        if (!response.ok) throw new Error('Failed to save revision');

        const result = await response.json();
        closeModal();

        if (result.is_new) {
            alert(`新しいリビジョン ${result.revision} を作成しました / New revision ${result.revision} created`);
        } else {
            alert('変更がありませんでした / No changes detected');
        }
    } catch (error) {
        alert(`エラー / Error: ${error.message}`);
    }
}

/**
 * Show batch edit parser modal
 * Enhanced with revision selector, restore button, and CSV converter (same as single execution)
 */
async function showBatchEditParserModal() {
    const projectId = document.getElementById('batch-project-select').value;
    if (!projectId) {
        alert('プロジェクトを選択してください / Please select a project');
        return;
    }

    try {
        // Fetch project and revisions in parallel
        const [projectResponse, revisionsResponse] = await Promise.all([
            fetch(`/api/projects/${projectId}`),
            fetch(`/api/projects/${projectId}/revisions`)
        ]);

        if (!projectResponse.ok) throw new Error('Failed to load project');
        const project = await projectResponse.json();
        const revisions = revisionsResponse.ok ? await revisionsResponse.json() : [];

        // Build revision selector options
        const revisionOptions = revisions.map(rev => {
            const date = formatJST(rev.created_at);
            const isCurrent = rev.revision === project.revision_count;
            return `<option value="${rev.revision}" ${isCurrent ? 'selected' : ''}>
                Rev.${rev.revision} (${date})${isCurrent ? ' - 現在' : ''}
            </option>`;
        }).join('');

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
                <div class="form-group" style="display: flex; align-items: center; gap: 10px;">
                    <label style="margin: 0;">リビジョン / Revision:</label>
                    <select id="batch-revision-selector" onchange="loadBatchRevisionContent(this.value, 'parser', ${projectId})" style="flex: 1;">
                        ${revisionOptions}
                    </select>
                    <button class="btn btn-secondary" onclick="restoreBatchRevision('parser', ${projectId})" style="background-color: #e67e22;" title="選択したリビジョンを復元 / Restore selected revision">
                        🔄 復元 / Restore
                    </button>
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
            <div class="modal-footer" style="display: flex; justify-content: space-between; flex-wrap: wrap; gap: 0.5rem;">
                <button class="btn" onclick="showJsonToCsvConverter()" style="background-color: #9b59b6;">📊 結果からCSVに変換 / Convert JSON to CSV</button>
                <div style="display: flex; gap: 0.5rem;">
                    <button class="btn btn-secondary" onclick="closeModal()">キャンセル / Cancel</button>
                    <button class="btn btn-primary" onclick="saveBatchParserRevision(${projectId})">保存 / Save</button>
                </div>
            </div>
        `;
        showModal(modalContent);
    } catch (error) {
        alert(`エラー / Error: ${error.message}`);
    }
}

/**
 * Save batch parser revision
 * Smart save: Creates new revision only if content changed
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

        if (!response.ok) throw new Error('Failed to save revision');

        const result = await response.json();
        closeModal();

        if (result.is_new) {
            alert(`新しいリビジョン ${result.revision} を作成しました / New revision ${result.revision} created`);
        } else {
            alert('変更がありませんでした / No changes detected');
        }
    } catch (error) {
        alert(`エラー / Error: ${error.message}`);
    }
}

/**
 * Load revision content for batch editor
 * @param {number} revisionNumber - The revision number to load
 * @param {string} type - 'prompt' or 'parser'
 * @param {number} projectId - The project ID
 */
async function loadBatchRevisionContent(revisionNumber, type, projectId) {
    try {
        const response = await fetch(`/api/projects/${projectId}/revisions`);
        if (!response.ok) throw new Error('Failed to load revisions');

        const revisions = await response.json();
        const revision = revisions.find(r => r.revision === parseInt(revisionNumber));

        if (!revision) {
            alert('リビジョンが見つかりません / Revision not found');
            return;
        }

        if (type === 'prompt') {
            document.getElementById('edit-prompt-template').value = revision.prompt_template;
        } else if (type === 'parser') {
            const parserConfig = revision.parser_config ? JSON.parse(revision.parser_config) : {type: 'none'};
            document.getElementById('edit-parser-type').value = parserConfig.type || 'none';
            document.getElementById('edit-parser-config').value = JSON.stringify(parserConfig, null, 2);
        }
    } catch (error) {
        alert(`エラー / Error: ${error.message}`);
    }
}

/**
 * Restore a past revision for batch editor (creates new revision with old content)
 * @param {string} type - 'prompt' or 'parser'
 * @param {number} projectId - The project ID
 */
async function restoreBatchRevision(type, projectId) {
    const selector = document.getElementById('batch-revision-selector');
    if (!selector) {
        alert('リビジョンセレクタが見つかりません / Revision selector not found');
        return;
    }

    const revisionNumber = parseInt(selector.value);
    const selectedOption = selector.options[selector.selectedIndex];
    const isCurrent = selectedOption.text.includes('現在');

    if (isCurrent) {
        alert('現在のリビジョンは復元できません（既に最新です）\nCannot restore current revision (already latest)');
        return;
    }

    if (!confirm(`リビジョン ${revisionNumber} を復元しますか？\n新しいリビジョンとして作成されます。\n\nRestore revision ${revisionNumber}?\nThis will create a new revision.`)) {
        return;
    }

    try {
        // Get the revision content
        const revisionsResponse = await fetch(`/api/projects/${projectId}/revisions`);
        if (!revisionsResponse.ok) throw new Error('Failed to load revisions');

        const revisions = await revisionsResponse.json();
        const revision = revisions.find(r => r.revision === revisionNumber);

        if (!revision) {
            alert('リビジョンが見つかりません / Revision not found');
            return;
        }

        // Create new revision with old content
        const restoreResponse = await fetch(`/api/projects/${projectId}/revisions/latest`, {
            method: 'PUT',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({
                prompt_template: revision.prompt_template,
                parser_config: revision.parser_config
            })
        });

        if (!restoreResponse.ok) throw new Error('Failed to restore revision');

        const result = await restoreResponse.json();
        closeModal();
        alert(`リビジョン ${revisionNumber} を復元しました（新しいリビジョン: ${result.revision}）\nRevision ${revisionNumber} restored (new revision: ${result.revision})`);
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
        // Reset pagination state
        batchHistoryOffset = 0;
        batchHistoryHasMore = true;

        // Get jobs for this project using new API with pagination
        const response = await fetch(`/api/projects/${projectId}/jobs?limit=${BATCH_HISTORY_PAGE_SIZE}&offset=0`);
        const allJobs = await response.json();

        // Check if we got fewer items than requested
        if (allJobs.length < BATCH_HISTORY_PAGE_SIZE) {
            batchHistoryHasMore = false;
        }

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
let batchHistoryOffset = 0;
const BATCH_HISTORY_PAGE_SIZE = 10;
let batchHistoryHasMore = true;

function renderBatchHistory(jobs, append = false) {
    const container = document.getElementById('batch-jobs-list');
    if (!container) return;

    // Store jobs for later use
    if (append) {
        currentBatchJobs = [...currentBatchJobs, ...(jobs || [])];
    } else {
        currentBatchJobs = jobs || [];
    }

    if (!currentBatchJobs || currentBatchJobs.length === 0) {
        container.innerHTML = '<p class="info">バッチジョブの履歴はまだありません / No batch jobs yet</p>';
        return;
    }

    const jobsToRender = append ? jobs : currentBatchJobs;

    const jobsHtml = jobsToRender.map(job => {
        const createdAt = formatJST(job.created_at);
        const finishedAt = formatJST(job.finished_at);
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

    if (append) {
        // Remove existing load-more link first
        const existingLoadMore = container.querySelector('.load-more-link');
        if (existingLoadMore) existingLoadMore.remove();
        // Append new jobs
        container.insertAdjacentHTML('beforeend', jobsHtml);
    } else {
        container.innerHTML = jobsHtml;
    }

    // Add "Load more" link if there might be more jobs
    if (batchHistoryHasMore) {
        const loadMoreHtml = `
            <div class="load-more-link" onclick="loadMoreBatchHistory()">
                <span>さらに表示... / Load more...</span>
            </div>
        `;
        container.insertAdjacentHTML('beforeend', loadMoreHtml);
    }

    // Add click event listeners after rendering
    document.querySelectorAll('#batch-jobs-list .history-item').forEach(item => {
        item.addEventListener('click', () => {
            const jobId = parseInt(item.dataset.jobId);
            selectBatchJob(jobId);
        });
    });
}

async function loadMoreBatchHistory() {
    const projectId = document.getElementById('batch-project-select')?.value;
    if (!projectId) return;

    batchHistoryOffset += BATCH_HISTORY_PAGE_SIZE;

    try {
        const response = await fetch(`/api/projects/${projectId}/jobs?limit=${BATCH_HISTORY_PAGE_SIZE}&offset=${batchHistoryOffset}`);
        const allJobs = await response.json();
        const batchJobs = allJobs.filter(job => job.job_type === 'batch');

        // Check if we got fewer items than requested (no more to load)
        if (allJobs.length < BATCH_HISTORY_PAGE_SIZE) {
            batchHistoryHasMore = false;
        }

        renderBatchHistory(batchJobs, true);
    } catch (error) {
        console.error('Failed to load more batch history:', error);
    }
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
                リビジョン数: ${project.revision_count} | 作成日: ${formatJST(project.created_at)}
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
        let defaultLoaded = false;
        try {
            const response = await fetch('/api/settings/default-project');
            const data = await response.json();
            if (data.project_id) {
                singleSelect.value = data.project_id;
                currentProjectId = data.project_id;
                // Trigger project change to load prompts
                await onProjectChange();
                defaultLoaded = true;
            }
        } catch (error) {
            console.error('Failed to load default project:', error);
        }

        // Fallback: if no default project, load config for first project in list
        if (!defaultLoaded && singleSelect.value) {
            currentProjectId = parseInt(singleSelect.value);
            await loadConfig(currentProjectId);
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

        // Also load model configuration settings
        await loadModelConfigurationSettings();
    } catch (error) {
        // Failed to load models - silently continue
    }
}

/**
 * Load unified model configuration settings
 * Shows enable/disable toggle and parameters for each model
 */
async function loadModelConfigurationSettings() {
    const container = document.getElementById('model-configuration-settings');
    if (!container) return;

    try {
        // Load all models with their status
        const modelsResponse = await fetch('/api/settings/models/all');
        const models = await modelsResponse.json();

        // Load parameters for each model
        const modelsWithParams = await Promise.all(
            models.map(async (model) => {
                try {
                    const paramsResponse = await fetch(`/api/settings/models/${model.name}/parameters`);
                    if (!paramsResponse.ok) return { ...model, parameters: null };
                    const paramsData = await paramsResponse.json();
                    return {
                        ...model,
                        parameters: paramsData.active_parameters || paramsData.default_parameters || {},
                        defaultParameters: paramsData.default_parameters || {}
                    };
                } catch (e) {
                    return { ...model, parameters: null };
                }
            })
        );

        container.innerHTML = modelsWithParams.map(model => {
            const isAzureGPT5 = model.name.includes('azure-gpt-5');
            const isOpenAIGPT5 = model.name.includes('openai-gpt-5');
            const params = model.parameters || {};
            const defaultParams = model.defaultParameters || {};

            // Build parameter inputs based on model type
            let paramInputs = '';

            // Azure GPT-5 models: show max_output_tokens
            if (isAzureGPT5) {
                const maxTokens = params.max_output_tokens || defaultParams.max_output_tokens || 8192;
                paramInputs = `
                    <div style="display: flex; align-items: center; gap: 0.5rem; margin-top: 0.5rem; flex-wrap: wrap;">
                        <span style="color: #7f8c8d; font-size: 0.85rem; min-width: 130px;">max_output_tokens:</span>
                        <input type="number"
                               id="param-max_output_tokens-${model.name}"
                               value="${maxTokens}"
                               min="1024"
                               max="65536"
                               step="1024"
                               style="width: 100px;">
                        <button class="btn btn-primary btn-sm"
                                onclick="saveModelParameter('${model.name}', 'max_output_tokens')"
                                style="padding: 0.25rem 0.5rem; font-size: 0.8rem;">
                            保存
                        </button>
                        <span id="param-status-${model.name}" style="color: #27ae60; font-size: 0.85rem;"></span>
                    </div>
                `;
            }
            // OpenAI GPT-5 models: show verbosity and reasoning_effort
            else if (isOpenAIGPT5) {
                const verbosity = params.verbosity || defaultParams.verbosity || 'medium';
                const reasoningEffort = params.reasoning_effort || defaultParams.reasoning_effort || 'minimal';
                paramInputs = `
                    <div style="display: flex; align-items: center; gap: 0.5rem; margin-top: 0.5rem; flex-wrap: wrap;">
                        <span style="color: #7f8c8d; font-size: 0.85rem; min-width: 80px;">verbosity:</span>
                        <select id="param-verbosity-${model.name}" style="width: 100px;">
                            <option value="low" ${verbosity === 'low' ? 'selected' : ''}>low</option>
                            <option value="medium" ${verbosity === 'medium' ? 'selected' : ''}>medium</option>
                            <option value="high" ${verbosity === 'high' ? 'selected' : ''}>high</option>
                        </select>
                        <span style="color: #7f8c8d; font-size: 0.85rem; min-width: 110px; margin-left: 0.5rem;">reasoning_effort:</span>
                        <select id="param-reasoning_effort-${model.name}" style="width: 100px;">
                            <option value="minimal" ${reasoningEffort === 'minimal' ? 'selected' : ''}>minimal</option>
                            <option value="medium" ${reasoningEffort === 'medium' ? 'selected' : ''}>medium</option>
                        </select>
                        <button class="btn btn-primary btn-sm"
                                onclick="saveOpenAIGPT5Parameters('${model.name}')"
                                style="padding: 0.25rem 0.5rem; font-size: 0.8rem; margin-left: 0.5rem;">
                            保存
                        </button>
                        <span id="param-status-${model.name}" style="color: #27ae60; font-size: 0.85rem;"></span>
                    </div>
                `;
            }
            // GPT-4 and other models: show temperature if available
            else if (params.temperature !== undefined || defaultParams.temperature !== undefined) {
                const temp = params.temperature !== undefined ? params.temperature : (defaultParams.temperature || 0.7);
                paramInputs = `
                    <div style="display: flex; align-items: center; gap: 0.5rem; margin-top: 0.5rem; flex-wrap: wrap;">
                        <span style="color: #7f8c8d; font-size: 0.85rem; min-width: 100px;">temperature:</span>
                        <input type="number"
                               id="param-temperature-${model.name}"
                               value="${temp}"
                               min="0"
                               max="2"
                               step="0.1"
                               style="width: 80px;">
                        <button class="btn btn-primary btn-sm"
                                onclick="saveModelParameter('${model.name}', 'temperature')"
                                style="padding: 0.25rem 0.5rem; font-size: 0.8rem;">
                            保存
                        </button>
                        <span id="param-status-${model.name}" style="color: #27ae60; font-size: 0.85rem;"></span>
                    </div>
                `;
            }

            return `
                <div class="model-config-item" style="padding: 0.75rem; border-bottom: 1px solid #ecf0f1;">
                    <div style="display: flex; align-items: center; justify-content: space-between;">
                        <label style="flex: 1; margin: 0; cursor: pointer; display: flex; align-items: center;">
                            <input type="checkbox"
                                   class="model-enable-checkbox"
                                   data-model-name="${model.name}"
                                   ${model.enabled ? 'checked' : ''}
                                   onchange="toggleModelEnabled('${model.name}', this.checked)"
                                   style="margin-right: 0.5rem; cursor: pointer; width: 18px; height: 18px;">
                            <strong>${model.display_name}</strong>
                            <span style="color: #7f8c8d; font-size: 0.85rem; margin-left: 0.5rem;">(${model.name})</span>
                        </label>
                        <span class="badge ${model.enabled ? 'badge-success' : 'badge-secondary'}" style="font-size: 0.75rem;">
                            ${model.enabled ? '有効' : '無効'}
                        </span>
                    </div>
                    ${paramInputs}
                </div>
            `;
        }).join('');

        // Add help text at bottom
        container.innerHTML += `
            <p class="info" style="margin-top: 1rem; font-size: 0.85rem; color: #7f8c8d;">
                <strong>Azure GPT-5:</strong> max_output_tokens 推奨値 8192〜16384（出力が切れる場合は増加）<br>
                <strong>OpenAI GPT-5:</strong> verbosity (low/medium/high), reasoning_effort (minimal/medium)<br>
                <strong>GPT-4:</strong> temperature 0.0〜2.0（低い値=確定的、高い値=創造的）
            </p>
        `;

    } catch (error) {
        container.innerHTML = '<p class="error">モデル設定の読み込みに失敗しました / Failed to load model settings</p>';
    }
}

/**
 * Toggle model enabled/disabled status
 */
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
        await loadModelConfigurationSettings();

    } catch (error) {
        alert(`エラー / Error: ${error.message}`);
        // Reload to reset checkbox state
        await loadModelConfigurationSettings();
    }
}

/**
 * Save a single model parameter
 */
async function saveModelParameter(modelName, paramName) {
    const input = document.getElementById(`param-${paramName}-${modelName}`);
    const statusSpan = document.getElementById(`param-status-${modelName}`);

    if (!input) return;

    let value = parseFloat(input.value);
    if (paramName === 'max_output_tokens') {
        value = parseInt(input.value, 10);
        if (isNaN(value) || value < 1024 || value > 65536) {
            alert('max_output_tokens は 1024 から 65536 の間で指定してください');
            return;
        }
    } else if (paramName === 'temperature') {
        if (isNaN(value) || value < 0 || value > 2) {
            alert('temperature は 0 から 2 の間で指定してください');
            return;
        }
    }

    try {
        const response = await fetch(`/api/settings/models/${modelName}/parameters`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ [paramName]: value })
        });

        if (!response.ok) {
            throw new Error('Failed to save parameter');
        }

        // Show success feedback
        if (statusSpan) {
            statusSpan.textContent = '✓ 保存完了';
            setTimeout(() => { statusSpan.textContent = ''; }, 3000);
        }

    } catch (error) {
        alert(`エラー / Error: ${error.message}`);
    }
}

/**
 * Save OpenAI GPT-5 parameters (verbosity and reasoning_effort)
 */
async function saveOpenAIGPT5Parameters(modelName) {
    const verbositySelect = document.getElementById(`param-verbosity-${modelName}`);
    const reasoningSelect = document.getElementById(`param-reasoning_effort-${modelName}`);
    const statusSpan = document.getElementById(`param-status-${modelName}`);

    if (!verbositySelect || !reasoningSelect) return;

    const verbosity = verbositySelect.value;
    const reasoningEffort = reasoningSelect.value;

    try {
        const response = await fetch(`/api/settings/models/${modelName}/parameters`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                verbosity: verbosity,
                reasoning_effort: reasoningEffort
            })
        });

        if (!response.ok) {
            throw new Error('Failed to save parameters');
        }

        // Show success feedback
        if (statusSpan) {
            statusSpan.textContent = '✓ 保存完了';
            setTimeout(() => { statusSpan.textContent = ''; }, 3000);
        }

    } catch (error) {
        alert(`エラー / Error: ${error.message}`);
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
                ファイル: ${dataset.source_file_name} | 行数: ${dataset.row_count} | 作成日: ${formatJST(dataset.created_at)}
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

        // Helper function for escaping HTML in this context
        function escapeHtml(unsafe) {
            if (unsafe === null || unsafe === undefined) return '';
            return String(unsafe)
                .replace(/&/g, "&amp;")
                .replace(/</g, "&lt;")
                .replace(/>/g, "&gt;")
                .replace(/"/g, "&quot;")
                .replace(/'/g, "&#039;");
        }

        const rowsHtml = preview.rows.map(row => {
            const cells = preview.columns.map(col => {
                const cellValue = row[col];
                const displayValue = escapeHtml(cellValue) || '';
                // Add title attribute for tooltip showing full content on hover
                const tooltipValue = String(cellValue ?? '').replace(/"/g, '&quot;');
                return `<td title="${tooltipValue}" style="border: 1px solid #ddd; padding: 8px;">${displayValue}</td>`;
            }).join('');
            return `<tr>${cells}</tr>`;
        }).join('');

        showModal(`
            <div class="modal-header" style="display: flex; justify-content: space-between; align-items: center;">
                <span>データセットプレビュー / Dataset Preview: ${preview.name}</span>
                <button onclick="closeModal()" style="background: none; border: none; font-size: 1.5rem; cursor: pointer; color: #7f8c8d; padding: 0 0.5rem;" title="閉じる / Close">×</button>
            </div>
            <div class="modal-body">
                <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 1rem; flex-wrap: wrap; gap: 0.5rem;">
                    <p style="margin: 0;">総行数 / Total Rows: ${preview.total_count}</p>
                    <div style="display: flex; gap: 1rem; flex-wrap: wrap;">
                        <label style="display: flex; align-items: center; gap: 0.3rem; cursor: pointer; user-select: none;">
                            <input type="checkbox" id="preview-truncate" checked onchange="togglePreviewTruncate(this.checked)">
                            <span style="font-size: 0.9rem;">折り返し省略 / Truncate</span>
                        </label>
                        <label style="display: flex; align-items: center; gap: 0.3rem; cursor: pointer; user-select: none;">
                            <input type="checkbox" id="preview-sticky-header" checked onchange="togglePreviewStickyHeader(this.checked)">
                            <span style="font-size: 0.9rem;">ヘッダ固定 / Fix Header</span>
                        </label>
                        <label style="display: flex; align-items: center; gap: 0.3rem; cursor: pointer; user-select: none;">
                            <input type="checkbox" id="preview-grid-lines" checked onchange="togglePreviewGridLines(this.checked)">
                            <span style="font-size: 0.9rem;">罫線表示 / Grid Lines</span>
                        </label>
                    </div>
                </div>
                <div id="preview-table-container" style="overflow-x: auto; max-height: 60vh; overflow-y: auto;">
                    <table id="preview-table" style="width: 100%; border-collapse: collapse;">
                        <thead>
                            <tr>${preview.columns.map(col => `<th style="border: 1px solid #ddd; padding: 8px; background: #f8f9fa;">${escapeHtml(col)}</th>`).join('')}</tr>
                        </thead>
                        <tbody>${rowsHtml}</tbody>
                    </table>
                </div>
            </div>
            <div class="modal-footer">
                <button class="btn btn-primary" onclick="closeModal()">閉じる / Close</button>
            </div>
        `);

        // Apply default styles (all checkboxes checked by default)
        togglePreviewTruncate(true);
        togglePreviewStickyHeader(true);
        togglePreviewGridLines(true);
    } catch (error) {
        alert(`エラー / Error: ${error.message}`);
    }
}

/**
 * Toggle truncate mode for dataset preview table
 */
function togglePreviewTruncate(enabled) {
    const table = document.getElementById('preview-table');
    if (!table) return;

    const cells = table.querySelectorAll('td');
    cells.forEach(cell => {
        if (enabled) {
            cell.style.maxWidth = '200px';
            cell.style.whiteSpace = 'nowrap';
            cell.style.overflow = 'hidden';
            cell.style.textOverflow = 'ellipsis';
        } else {
            cell.style.maxWidth = '';
            cell.style.whiteSpace = '';
            cell.style.overflow = '';
            cell.style.textOverflow = '';
        }
    });
}

/**
 * Toggle sticky header for dataset preview table
 */
function togglePreviewStickyHeader(enabled) {
    const table = document.getElementById('preview-table');
    if (!table) return;

    const thead = table.querySelector('thead');
    const headerCells = table.querySelectorAll('th');

    if (enabled) {
        thead.style.position = 'sticky';
        thead.style.top = '0';
        thead.style.zIndex = '10';
        headerCells.forEach(th => {
            th.style.background = '#f8f9fa';
            th.style.boxShadow = '0 2px 4px rgba(0,0,0,0.1)';
        });
    } else {
        thead.style.position = '';
        thead.style.top = '';
        thead.style.zIndex = '';
        headerCells.forEach(th => {
            th.style.boxShadow = '';
        });
    }
}

/**
 * Toggle grid lines and zebra striping for dataset preview table
 */
function togglePreviewGridLines(enabled) {
    const table = document.getElementById('preview-table');
    if (!table) return;

    const allCells = table.querySelectorAll('th, td');
    const rows = table.querySelectorAll('tbody tr');

    if (enabled) {
        // Add colored borders to all cells
        allCells.forEach(cell => {
            cell.style.border = '1px solid #3498db';
        });
        // Add zebra striping (odd rows get light blue background)
        rows.forEach((row, index) => {
            if (index % 2 === 0) {
                row.style.background = '#ebf5fb';
            } else {
                row.style.background = '#ffffff';
            }
        });
    } else {
        // Reset to default borders
        allCells.forEach(cell => {
            cell.style.border = '1px solid #ddd';
        });
        // Reset row backgrounds
        rows.forEach(row => {
            row.style.background = '';
        });
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

function showModal2(content) {
    const modal = document.getElementById('modal-overlay-2');
    const modalContent = document.getElementById('modal-content-2');
    if (modal && modalContent) {
        modalContent.innerHTML = content;
        modal.classList.add('show');
    }
}

function closeModal2() {
    const modal = document.getElementById('modal-overlay-2');
    if (modal) {
        modal.classList.remove('show');
    }
}

function showParserHelp() {
    const helpContent = `
        <div class="modal-header" style="display: flex; justify-content: space-between; align-items: center;">
            <span>パーサー設定ヘルプ / Parser Configuration Help</span>
            <button class="btn btn-secondary" onclick="closeModal2()" style="margin: 0;">閉じる / Close</button>
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
    `;
    showModal2(helpContent);
}

function showPromptTemplateHelp() {
    const helpContent = `
        <div class="modal-header" style="display: flex; justify-content: space-between; align-items: center;">
            <span>プロンプトテンプレート構文ヘルプ / Prompt Template Syntax Help</span>
            <button class="btn btn-secondary" onclick="closeModal2()" style="margin: 0;">閉じる / Close</button>
        </div>
        <div class="modal-body" style="max-height: 75vh; overflow-y: auto; overflow-x: auto;">
            <h3 style="color: #2c3e50; border-bottom: 2px solid #3498db; padding-bottom: 0.5rem;">📖 プロンプトテンプレート構文の概要 / Prompt Template Syntax Overview</h3>
            <p style="margin: 1rem 0;">
                プロンプトテンプレートは、動的なパラメータを含むテキストです。<br>
                <code>{{ }}</code> で囲まれた部分がパラメータとして自動的に入力フォームに変換されます。
            </p>
            <p style="margin: 1rem 0; font-style: italic; color: #7f8c8d;">
                Prompt templates are text with dynamic parameters.<br>
                Parts enclosed in <code>{{ }}</code> are automatically converted to input forms.
            </p>

            <h3 style="color: #2c3e50; border-bottom: 2px solid #3498db; padding-bottom: 0.5rem; margin-top: 2rem;">📝 基本構文 / Basic Syntax</h3>

            <h4 style="color: #27ae60; margin-top: 1rem;">必須パラメータ / Required Parameters</h4>
            <pre style="background: #f8f9fa; padding: 1rem; border-radius: 4px; overflow-x: auto;"><code>{{PARAM_NAME:TYPE}}</code></pre>
            <ul style="margin: 0.5rem 0 1rem 2rem;">
                <li>ユーザーは必ず値を入力する必要があります / User must provide a value</li>
                <li>入力フォームに赤いアスタリスク (<span style="color: #e74c3c;">*</span>) が表示されます / Red asterisk displayed in form</li>
                <li>例 / Example: <code>{{name:TEXT1}}</code> → 1行テキスト入力（必須）</li>
            </ul>

            <h4 style="color: #27ae60; margin-top: 1rem;">任意パラメータ（デフォルト値なし）/ Optional Parameters (No Default)</h4>
            <pre style="background: #f8f9fa; padding: 1rem; border-radius: 4px; overflow-x: auto;"><code>{{PARAM_NAME:TYPE|}}</code></pre>
            <ul style="margin: 0.5rem 0 1rem 2rem;">
                <li><strong>重要:</strong> パラメータ名の後に <code>|</code> (パイプ) を付けます / Add <code>|</code> (pipe) after parameter name</li>
                <li>ユーザーは空欄のまま実行できます / User can leave blank</li>
                <li>アスタリスクは表示されません / No asterisk displayed</li>
                <li>例 / Example: <code>{{phone:TEXT1|}}</code> → 1行テキスト入力（任意、空欄可）</li>
            </ul>

            <h4 style="color: #27ae60; margin-top: 1rem;">任意パラメータ（デフォルト値あり）/ Optional Parameters (With Default)</h4>
            <pre style="background: #f8f9fa; padding: 1rem; border-radius: 4px; overflow-x: auto;"><code>{{PARAM_NAME:TYPE|default=値}}</code></pre>
            <ul style="margin: 0.5rem 0 1rem 2rem;">
                <li><code>|default=</code> の後にデフォルト値を指定 / Specify default value after <code>|default=</code></li>
                <li>ユーザーが空欄の場合、デフォルト値が使用されます / Default value used if left blank</li>
                <li>入力フォームに初期値として表示されます / Displayed as initial value in form</li>
                <li>例 / Example: <code>{{preferred_time:TEXT1|default=平日10-18時}}</code></li>
            </ul>

            <h4 style="color: #27ae60; margin-top: 1rem;">タイプ省略時のデフォルト / Default When Type Omitted</h4>
            <pre style="background: #f8f9fa; padding: 1rem; border-radius: 4px; overflow-x: auto;"><code>{{PARAM_NAME}}</code></pre>
            <ul style="margin: 0.5rem 0 1rem 2rem;">
                <li>タイプを省略すると、デフォルトで <code>TEXT5</code>（5行テキストエリア、必須）になります</li>
                <li>If type is omitted, defaults to <code>TEXT5</code> (5-line textarea, required)</li>
            </ul>

            <h3 style="color: #2c3e50; border-bottom: 2px solid #3498db; padding-bottom: 0.5rem; margin-top: 2rem;">📌 パラメータタイプ一覧 / Parameter Types</h3>

            <h4 style="color: #27ae60; margin-top: 1rem;">テキスト入力 / Text Input</h4>
            <ul style="margin: 0.5rem 0 1rem 2rem;">
                <li><strong>TEXT1 〜 TEXT20</strong>: テキストエリア（1〜20行）/ Textarea (1-20 lines)</li>
                <li>例 / Example: <code>{{description:TEXT5}}</code> → 5行のテキストエリア</li>
            </ul>

            <h4 style="color: #27ae60; margin-top: 1rem;">数値・日時入力 / Numeric & DateTime Input</h4>
            <ul style="margin: 0.5rem 0 1rem 2rem;">
                <li><strong>NUM</strong>: 数値入力 / Number input</li>
                <li><strong>DATE</strong>: 日付選択 / Date picker (YYYY-MM-DD)</li>
                <li><strong>DATETIME</strong>: 日時選択 / DateTime picker (YYYY-MM-DD HH:MM)</li>
            </ul>

            <h4 style="color: #27ae60; margin-top: 1rem;">画像・ファイル入力 / Image & File Input</h4>
            <ul style="margin: 0.5rem 0 1rem 2rem;">
                <li><strong>FILE</strong>: 画像アップロード（Vision API対応）/ Image upload (Vision API compatible)
                    <ul style="margin-top: 0.3rem;">
                        <li>対応形式 / Supported: JPEG, PNG, GIF, WebP</li>
                        <li>最大サイズ / Max size: 20MB</li>
                        <li>ブラウザから画像をアップロードして、LLMのVision APIに送信 / Upload from browser and send to Vision API</li>
                        <li>ドラッグ＆ドロップ対応 / Drag & drop supported</li>
                    </ul>
                </li>
                <li><strong>FILEPATH</strong>: サーバーファイルパス（バッチ処理用）/ Server file path (for batch processing)
                    <ul style="margin-top: 0.3rem;">
                        <li>サーバー上のファイルパスを指定 / Specify file path on server</li>
                        <li>バッチ実行時、データセットにファイルパスを記載して使用 / Use by specifying file paths in dataset for batch execution</li>
                    </ul>
                </li>
            </ul>

            <h3 style="color: #2c3e50; border-bottom: 2px solid #3498db; padding-bottom: 0.5rem; margin-top: 2rem;">✨ 実例 / Complete Examples</h3>

            <h4 style="color: #27ae60; margin-top: 1rem;">例1: お問い合わせフォーム / Example 1: Contact Form</h4>
            <pre style="background: #f8f9fa; padding: 1rem; border-radius: 4px; overflow-x: auto; white-space: pre-wrap;"><code>以下の情報に基づいてお問い合わせメールを作成してください。

【必須項目】
お名前: {{name:TEXT1}}
メールアドレス: {{email:TEXT1}}
お問い合わせ内容: {{inquiry:TEXT5}}

【任意項目】
電話番号: {{phone:TEXT1|}}
会社名: {{company:TEXT1|}}
希望連絡時間: {{preferred_time:TEXT1|default=平日10-18時}}
備考: {{notes:TEXT5|default=特になし}}</code></pre>

            <h4 style="color: #27ae60; margin-top: 1rem;">例2: 画像分析プロンプト / Example 2: Image Analysis Prompt</h4>
            <pre style="background: #f8f9fa; padding: 1rem; border-radius: 4px; overflow-x: auto; white-space: pre-wrap;"><code>添付された画像を分析してください。

画像ファイル: {{image:FILE}}
分析の観点: {{analysis_focus:TEXT1|default=全体的な内容と特徴}}

上記の観点で、画像の内容を詳しく説明してください。</code></pre>

            <div style="background: #e8f8f5; border-left: 4px solid #27ae60; padding: 1rem; margin: 1.5rem 0;">
                <strong>💡 ヒント / Tips:</strong>
                <ul style="margin: 0.5rem 0 0 1.5rem;">
                    <li>必須項目は最小限にして、ユーザーの入力負担を減らしましょう</li>
                    <li>Minimize required fields to reduce user input burden</li>
                    <li>デフォルト値を設定すると、入力の手間が省けます</li>
                    <li>Setting default values saves input effort</li>
                    <li>同じパラメータ名を複数箇所で使用すると、同じ値が展開されます</li>
                    <li>Using the same parameter name in multiple places expands to the same value</li>
                </ul>
            </div>
        </div>
    `;
    showModal2(helpContent);
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

        // Check model type
        const isGPT5 = modelName.includes('gpt-5') || modelName.includes('gpt5');
        const isAzureGPT5 = isGPT5 && modelName.includes('azure');
        const isOpenAIGPT5 = isGPT5 && modelName.includes('openai');

        // Get all parameter groups
        const temperatureGroup = document.getElementById('param-temperature-group');
        const maxTokensGroup = document.getElementById('param-max-tokens-group');
        const topPGroup = document.getElementById('param-top-p-group');
        const maxOutputTokensGroup = document.getElementById('param-max-output-tokens-group');
        const verbosityGroup = document.getElementById('param-verbosity-group');
        const reasoningEffortGroup = document.getElementById('param-reasoning-effort-group');

        if (isAzureGPT5) {
            // Azure GPT-5: Show max_output_tokens only
            temperatureGroup.style.display = 'none';
            maxTokensGroup.style.display = 'none';
            topPGroup.style.display = 'none';
            maxOutputTokensGroup.style.display = 'block';
            verbosityGroup.style.display = 'none';
            reasoningEffortGroup.style.display = 'none';

            // Set Azure GPT-5 parameter values
            document.getElementById('param-max-output-tokens').value = active.max_output_tokens || defaults.max_output_tokens || 8192;
            document.getElementById('default-max-output-tokens').textContent = `(デフォルト / Default: ${defaults.max_output_tokens || 8192})`;
        } else if (isOpenAIGPT5) {
            // OpenAI GPT-5: Show verbosity and reasoning_effort
            temperatureGroup.style.display = 'none';
            maxTokensGroup.style.display = 'none';
            topPGroup.style.display = 'none';
            maxOutputTokensGroup.style.display = 'none';
            verbosityGroup.style.display = 'block';
            reasoningEffortGroup.style.display = 'block';

            // Set OpenAI GPT-5 parameter values
            document.getElementById('param-verbosity').value = active.verbosity || defaults.verbosity || 'medium';
            document.getElementById('param-reasoning-effort').value = active.reasoning_effort || defaults.reasoning_effort || 'medium';

            document.getElementById('default-verbosity').textContent = `(デフォルト / Default: ${defaults.verbosity || 'medium'})`;
            document.getElementById('default-reasoning-effort').textContent = `(デフォルト / Default: ${defaults.reasoning_effort || 'medium'})`;
        } else {
            // Non-GPT-5: Show traditional parameters
            temperatureGroup.style.display = 'block';
            maxTokensGroup.style.display = 'block';
            topPGroup.style.display = 'block';
            maxOutputTokensGroup.style.display = 'none';
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
    const isAzureGPT5 = isGPT5 && modelName.includes('azure');
    const isOpenAIGPT5 = isGPT5 && modelName.includes('openai');

    let parameters;

    if (isAzureGPT5) {
        // Azure GPT-5: Send max_output_tokens only
        parameters = {
            max_output_tokens: parseInt(document.getElementById('param-max-output-tokens').value)
        };
    } else if (isOpenAIGPT5) {
        // OpenAI GPT-5: Send verbosity and reasoning_effort
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

    // Use dedicated status element instead of batch-results-area to avoid overwriting results
    await cancelJob(currentBatchJobId, 'btn-stop-batch', 'batch-execution-status');
    hideBatchStopButton();

    // Show the status element
    const statusEl = document.getElementById('batch-execution-status');
    if (statusEl) {
        statusEl.style.display = 'block';
    }

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

/**
 * Show JSON to CSV template converter modal
 * Allows user to paste JSON sample and generate parser config automatically
 */
function showJsonToCsvConverter() {
    const converterContent = `
        <div class="modal-header" style="display: flex; justify-content: space-between; align-items: center;">
            <span>📊 JSON → CSV テンプレート変換 / JSON to CSV Template Converter</span>
            <button class="btn btn-secondary" onclick="closeModal2()" style="margin: 0;">閉じる / Close</button>
        </div>
        <div class="modal-body" style="max-height: 70vh; overflow-y: auto;">
            <div class="form-group">
                <label style="font-weight: bold;">1. サンプルJSONを貼り付け / Paste Sample JSON:</label>
                <textarea id="json-sample-input" rows="15" style="font-family: 'Courier New', monospace; width: 100%;" placeholder='{
  "field1": { "score": 1, "reason": "理由" },
  "field2": { "nested": { "value": "test" } }
}'></textarea>
                <small style="color: #7f8c8d;">
                    LLMからの期待されるJSON出力形式を貼り付けてください。<br>
                    Paste the expected JSON output format from the LLM.
                </small>
            </div>
            <div class="form-group" style="margin-top: 1rem;">
                <button class="btn btn-primary" onclick="convertJsonToCsvTemplate()" style="width: 100%;">
                    🔄 変換 / Convert
                </button>
            </div>
            <div class="form-group" style="margin-top: 1rem;">
                <label style="font-weight: bold;">2. 生成されたパーサー設定 / Generated Parser Config:</label>
                <textarea id="generated-parser-config" rows="15" style="font-family: 'Courier New', monospace; width: 100%;" readonly placeholder="変換後のパーサー設定がここに表示されます / Generated parser config will appear here"></textarea>
            </div>
            <div class="form-group" style="margin-top: 1rem;">
                <label style="font-weight: bold;">3. CSVヘッダープレビュー / CSV Header Preview:</label>
                <textarea id="csv-header-preview" rows="3" style="font-family: 'Courier New', monospace; width: 100%; background: #f8f9fa;" readonly placeholder="CSVヘッダーがここに表示されます / CSV header will appear here"></textarea>
            </div>
        </div>
        <div class="modal-footer">
            <button class="btn btn-secondary" onclick="closeModal2()">閉じる / Close</button>
            <button class="btn btn-primary" onclick="applyGeneratedParserConfig()" style="background-color: #27ae60;">
                ✅ パーサー設定に適用 / Apply to Parser Config
            </button>
        </div>
    `;
    showModal2(converterContent);
}

/**
 * Convert JSON sample to CSV template parser config
 * Recursively extracts all leaf paths from the JSON structure
 */
function convertJsonToCsvTemplate() {
    const jsonInput = document.getElementById('json-sample-input').value.trim();
    const outputArea = document.getElementById('generated-parser-config');
    const headerPreview = document.getElementById('csv-header-preview');

    if (!jsonInput) {
        alert('JSONを入力してください / Please enter JSON');
        return;
    }

    try {
        // Remove <...> placeholders and replace with sample values for parsing
        let cleanedJson = jsonInput
            // Handle "<...>" (quoted placeholder) -> "sample"
            .replace(/"<[^>]+>"/g, '"sample"')
            // Handle <...> (unquoted placeholder) -> "sample"
            .replace(/<[^>]+>/g, '"sample"')
            // Fix trailing commas
            .replace(/,\s*}/g, '}')
            .replace(/,\s*]/g, ']');

        const jsonData = JSON.parse(cleanedJson);

        // Extract all leaf paths
        const paths = {};
        const fieldNames = [];
        extractPaths(jsonData, '$', paths, fieldNames);

        // Generate CSV template
        const csvTemplate = fieldNames.map(name => '$' + name + '$').join(',');

        // Generate parser config
        const parserConfig = {
            type: 'json_path',
            paths: paths,
            csv_template: csvTemplate
        };

        outputArea.value = JSON.stringify(parserConfig, null, 2);
        headerPreview.value = fieldNames.join(',');

    } catch (error) {
        alert('JSONの解析に失敗しました / Failed to parse JSON: ' + error.message);
        outputArea.value = 'Error: ' + error.message;
        headerPreview.value = '';
    }
}

/**
 * Recursively extract paths from JSON object
 * @param {any} obj - Current object/value
 * @param {string} currentPath - Current JSON path (e.g., "$.field")
 * @param {object} paths - Output object for path mappings
 * @param {array} fieldNames - Output array for field names (in order)
 */
function extractPaths(obj, currentPath, paths, fieldNames) {
    if (obj === null || obj === undefined) {
        return;
    }

    if (typeof obj === 'object' && !Array.isArray(obj)) {
        // Object: recurse into properties
        for (const key of Object.keys(obj)) {
            const newPath = currentPath === '$' ? '$.' + key : currentPath + '.' + key;
            extractPaths(obj[key], newPath, paths, fieldNames);
        }
    } else if (Array.isArray(obj)) {
        // Array: skip arrays for now (complex to handle in CSV)
        // Could be extended to handle arrays if needed
    } else {
        // Leaf value (string, number, boolean)
        // Generate field name from path (replace dots with underscores)
        const fieldName = currentPath.replace(/^\$\./, '').replace(/\./g, '_');
        paths[fieldName] = currentPath;
        fieldNames.push(fieldName);
    }
}

/**
 * Apply generated parser config to the main parser config textarea
 */
function applyGeneratedParserConfig() {
    const generatedConfig = document.getElementById('generated-parser-config').value;

    if (!generatedConfig || generatedConfig.startsWith('Error:')) {
        alert('有効なパーサー設定がありません / No valid parser config available');
        return;
    }

    try {
        // Validate JSON
        const config = JSON.parse(generatedConfig);

        // Apply to main parser config
        const mainConfigArea = document.getElementById('edit-parser-config');
        const parserTypeSelect = document.getElementById('edit-parser-type');

        if (mainConfigArea && parserTypeSelect) {
            mainConfigArea.value = generatedConfig;
            parserTypeSelect.value = config.type || 'json_path';
        }

        closeModal2();
        alert('パーサー設定に適用しました。保存ボタンで保存してください。\n\nApplied to parser config. Click Save to save.');

    } catch (error) {
        alert('パーサー設定の適用に失敗しました / Failed to apply parser config: ' + error.message);
    }
}
