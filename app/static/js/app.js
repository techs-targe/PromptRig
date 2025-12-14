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
let allWorkflows = [];
let currentProjectId = 1;
let currentWorkflowId = null;
let currentPromptId = null;  // NEW ARCHITECTURE: ID of selected prompt
let currentSelectionType = 'project'; // 'project', 'workflow', or 'prompt'
let currentExecutionTargets = null;  // NEW ARCHITECTURE: Cache of prompts/workflows for current project

// History pagination state
let singleHistoryOffset = 0;
const SINGLE_HISTORY_PAGE_SIZE = 10;
let singleHistoryHasMore = true;

let batchHistoryOffset = 0;
const BATCH_HISTORY_PAGE_SIZE = 10;
let batchHistoryHasMore = true;

// Dataset preview state
let currentPreviewDatasetId = null;

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
 * Copy workflow CSV output to clipboard
 * @param {string} jobId - The workflow job ID
 */
function copyWorkflowCsv(jobId) {
    const textarea = document.getElementById(`workflow-csv-${jobId}`);
    if (!textarea) {
        alert('CSVデータが見つかりません / CSV data not found');
        return;
    }
    navigator.clipboard.writeText(textarea.value).then(() => {
        alert('CSVをクリップボードにコピーしました / CSV copied to clipboard');
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
            // NEW ARCHITECTURE: If a prompt/workflow is already selected, state is preserved
            // Don't reload as it would overwrite the selected prompt's config
            if (currentSelectionType === 'prompt' && currentPromptId) {
                // Already loaded, nothing to do
            } else if (currentSelectionType === 'workflow' && currentWorkflowId) {
                // Workflow already loaded
            } else if (currentProjectId) {
                // Reload execution targets which will auto-select first prompt
                loadExecutionTargets(currentProjectId);
            } else {
                // Fallback to old behavior
                loadConfig();
            }
            break;
        case 'batch':
            loadBatchJobs();
            break;
        case 'workflows':
            initWorkflowTab();
            break;
        case 'projects':
            loadProjects();
            break;
        case 'settings':
            loadSettings();
            loadAvailableModels();
            loadModelConfigurationSettings();
            loadJobParallelism();
            loadTextFileExtensions();
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
    document.getElementById('single-target-select')?.addEventListener('change', onExecutionTargetChange);  // NEW ARCHITECTURE
    document.getElementById('btn-edit-prompt')?.addEventListener('click', showEditPromptModal);
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
    document.getElementById('btn-reload-batch-history')?.addEventListener('click', async () => {
        const selectValue = document.getElementById('batch-project-select').value;
        if (selectValue) {
            const parsed = parseSelectValue(selectValue);
            if (parsed && parsed.type === 'project' && parsed.id) {
                await loadBatchJobHistory(parsed.id);
                // Re-select the previously selected batch job if any
                if (selectedBatchJobId) {
                    selectBatchJob(selectedBatchJobId);
                }
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

    // Text file extensions buttons
    document.getElementById('btn-save-text-extensions')?.addEventListener('click', saveTextFileExtensions);
    document.getElementById('btn-reset-text-extensions')?.addEventListener('click', resetTextFileExtensions);

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

        // Reset pagination state for single execution history
        singleHistoryOffset = 0;
        singleHistoryHasMore = true;

        // Get project details
        const projectResponse = await fetch(`/api/projects/${pid}`);
        if (!projectResponse.ok) throw new Error(`Failed to load project ${pid}`);
        const project = await projectResponse.json();

        // Get single-type jobs for this project (first page only)
        const jobsResponse = await fetch(`/api/projects/${pid}/jobs?limit=${SINGLE_HISTORY_PAGE_SIZE}&offset=0&job_type=single`);
        if (!jobsResponse.ok) throw new Error(`Failed to load jobs for project ${pid}`);
        const singleJobs = await jobsResponse.json();

        // Check if there might be more jobs
        singleHistoryHasMore = singleJobs.length >= SINGLE_HISTORY_PAGE_SIZE;
        singleHistoryOffset = singleJobs.length;

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

/**
 * Load configuration for workflow execution
 * Workflow shows combined prompt templates and parameters from all steps
 * Input parameters = Step1's prompt parameters + workflow input mapping parameters
 * @param {number} workflowId - Workflow ID
 */
async function loadWorkflowConfig(workflowId) {
    try {
        // Reset pagination state for single execution history
        singleHistoryOffset = 0;
        singleHistoryHasMore = true;

        // Get workflow details
        const workflowResponse = await fetch(`/api/workflows/${workflowId}`);
        if (!workflowResponse.ok) throw new Error(`Failed to load workflow ${workflowId}`);
        const workflow = await workflowResponse.json();

        // Get workflow jobs for history
        const jobsResponse = await fetch(`/api/workflows/${workflowId}/jobs?limit=${SINGLE_HISTORY_PAGE_SIZE}`);
        const workflowJobs = jobsResponse.ok ? await jobsResponse.json() : [];

        // Get first step's prompt to determine input parameters
        let firstStepPrompt = null;
        let parameters = [];
        const seenParams = new Set();

        if (workflow.steps && workflow.steps.length > 0) {
            const firstStep = workflow.steps[0];

            // New architecture: Get parameters from prompt using execution-targets API
            if (firstStep.prompt_id) {
                const targetsResponse = await fetch(`/api/projects/${firstStep.project_id}/execution-targets`);
                if (targetsResponse.ok) {
                    const targets = await targetsResponse.json();
                    firstStepPrompt = targets.prompts?.find(p => p.id === firstStep.prompt_id);
                    if (firstStepPrompt) {
                        // Add Step1's prompt parameters
                        for (const param of (firstStepPrompt.parameters || [])) {
                            if (!seenParams.has(param.name)) {
                                seenParams.add(param.name);
                                parameters.push(param);
                            }
                        }
                    }
                }
            }

            // Fallback: Old architecture - get from project's latest revision
            if (!firstStepPrompt) {
                const projectResponse = await fetch(`/api/projects/${firstStep.project_id}`);
                if (projectResponse.ok) {
                    const project = await projectResponse.json();
                    for (const param of (project.parameters || [])) {
                        if (!seenParams.has(param.name)) {
                            seenParams.add(param.name);
                            parameters.push(param);
                        }
                    }
                }
            }

            // Extract parameters from workflow step input mappings
            // Pattern: {{PARAM_NAME:TYPE}} that are NOT references like {{input.xxx}} or {{stepN.xxx}}
            for (const step of workflow.steps) {
                if (step.input_mapping) {
                    const mappingStr = typeof step.input_mapping === 'string'
                        ? step.input_mapping
                        : JSON.stringify(step.input_mapping);

                    // Find {{PARAM_NAME:TYPE}} patterns (NOT {{input.xxx}} or {{stepN_xxx}})
                    const regex = /\{\{([^}.]+):([^}]+)\}\}/g;
                    let match;
                    while ((match = regex.exec(mappingStr)) !== null) {
                        const paramName = match[1].trim();
                        const paramType = match[2].trim().toUpperCase();

                        // Skip if it's a reference like input.xxx or stepN.xxx
                        if (paramName.includes('.') || paramName.match(/^step\d+/i)) {
                            continue;
                        }

                        if (!seenParams.has(paramName)) {
                            seenParams.add(paramName);
                            parameters.push({
                                name: paramName,
                                type: paramType,
                                required: false  // Workflow input mapping params are optional
                            });
                        }
                    }
                }
            }
        }

        // Build combined prompt template display
        let combinedPrompt = `=== ワークフロー: ${workflow.name} ===\n`;
        combinedPrompt += `説明: ${workflow.description || '(なし)'}\n`;
        combinedPrompt += `ステップ数: ${workflow.steps.length}\n\n`;

        for (const step of workflow.steps) {
            combinedPrompt += `--- Step ${step.step_order}: ${step.step_name} ---\n`;
            combinedPrompt += `プロジェクト: ${step.project_name}\n`;
            if (step.input_mapping) {
                combinedPrompt += `入力マッピング: ${JSON.stringify(step.input_mapping)}\n`;
            }
            combinedPrompt += '\n';
        }

        // Build config object
        const firstStep = workflow.steps && workflow.steps.length > 0 ? workflow.steps[0] : null;
        currentConfig = {
            workflow_id: workflow.id,
            workflow_name: workflow.name,
            project_id: firstStep ? firstStep.project_id : null,
            project_name: firstStep ? firstStep.project_name : workflow.name,
            prompt_template: combinedPrompt,
            parameters: parameters,
            recent_jobs: workflowJobs.map(j => ({
                id: j.id,
                workflow_id: j.workflow_id,
                job_type: 'workflow',
                status: j.status,
                input_params: j.input_params,
                model_name: j.model_name,
                created_at: j.created_at,
                turnaround_ms: j.turnaround_ms
            })),
            available_models: ["azure-gpt-4.1", "openai-gpt-4.1-nano"],
            is_workflow: true
        };

        renderSingleExecutionTab();

        // Update history display to show workflow-specific jobs
        renderWorkflowHistory(workflowJobs);

    } catch (error) {
        console.error('Failed to load workflow config:', error);
        showStatus('ワークフローの読み込みに失敗しました / Failed to load workflow configuration', 'error');
    }
}

/**
 * Render workflow execution history
 * @param {Array} jobs - Workflow jobs
 */
function renderWorkflowHistory(jobs) {
    const container = document.getElementById('history-list');
    if (!container) return;

    if (!jobs || jobs.length === 0) {
        container.innerHTML = '<div class="history-item">履歴がありません / No history</div>';
        return;
    }

    container.innerHTML = jobs.map(job => `
        <div class="history-item ${selectedJobId === job.id ? 'selected' : ''}"
             onclick="selectWorkflowJob(${job.id})">
            <div class="history-item-header">
                <span class="history-item-id">WF-Job #${job.id}</span>
                <span class="history-item-status status-${job.status}">${job.status}</span>
            </div>
            <div class="history-item-time">${formatJST(job.created_at)}</div>
            <div class="history-item-model">${job.model_name || 'default'}</div>
            ${job.turnaround_ms ? `<div class="history-item-time">${job.turnaround_ms}ms</div>` : ''}
        </div>
    `).join('');
}

/**
 * Select and display workflow job results
 * @param {number} jobId - Workflow job ID
 */
async function selectWorkflowJob(jobId) {
    selectedJobId = jobId;

    // Update selection in history list
    document.querySelectorAll('.history-item').forEach(item => {
        item.classList.remove('selected');
        if (item.querySelector(`[onclick*="selectWorkflowJob(${jobId})"]`) || item.getAttribute('onclick')?.includes(`selectWorkflowJob(${jobId})`)) {
            item.classList.add('selected');
        }
    });

    // Highlight the selected item
    const historyItems = document.querySelectorAll('.history-item');
    historyItems.forEach(item => {
        if (item.getAttribute('onclick')?.includes(`selectWorkflowJob(${jobId})`)) {
            item.classList.add('selected');
        }
    });

    try {
        const response = await fetch(`/api/workflow-jobs/${jobId}`);
        if (!response.ok) throw new Error('Failed to fetch workflow job');
        const job = await response.json();

        // Populate input form with the job's input params
        if (job.input_params) {
            const params = typeof job.input_params === 'string'
                ? JSON.parse(job.input_params)
                : job.input_params;
            populateInputForm(params);
        }

        displayWorkflowJobResults(job);
    } catch (error) {
        console.error('Failed to load workflow job:', error);
        showStatus('ワークフロージョブの読み込みに失敗しました / Failed to load workflow job', 'error');
    }
}

/**
 * Display workflow job results
 * @param {Object} job - Workflow job data
 */
function displayWorkflowJobResults(job) {
    const container = document.getElementById('results-area');

    if (!container) return;

    // Build HTML output showing all step results
    let html = `
        <div class="workflow-job-results">
            <div class="workflow-job-header">
                <h4>ワークフロージョブ #${job.id}</h4>
                <span class="status-badge status-${job.status}">${job.status}</span>
            </div>
            <div class="workflow-job-meta">
                <span>モデル: ${escapeHtmlGlobal(job.model_name || 'default')}</span>
                <span>作成: ${formatJST(job.created_at)}</span>
                ${job.turnaround_ms ? `<span>処理時間: ${job.turnaround_ms}ms</span>` : ''}
            </div>
    `;

    // Display step results
    if (job.step_results && job.step_results.length > 0) {
        html += '<div class="workflow-steps">';
        for (const step of job.step_results) {
            html += `
                <div class="workflow-step">
                    <div class="step-header">
                        <span class="step-name">Step ${step.step_order}: ${escapeHtmlGlobal(step.step_name)}</span>
                        <span class="step-status status-${step.status}">${step.status}</span>
                        ${step.turnaround_ms ? `<span class="step-time">${step.turnaround_ms}ms</span>` : ''}
                    </div>
                    ${step.input_params && Object.keys(step.input_params).length > 0 ? `
                        <div class="step-input">
                            <h6>📤 送信 / Input</h6>
                            <pre>${escapeHtmlGlobal(JSON.stringify(step.input_params, null, 2))}</pre>
                        </div>
                    ` : '<div class="step-input"><h6>📤 送信 / Input</h6><pre>(なし / none)</pre></div>'}
                    ${step.output_fields ? `
                        <div class="step-output">
                            <h6>📥 受信 / Output</h6>
                            <pre>${escapeHtmlGlobal(JSON.stringify(step.output_fields, null, 2))}</pre>
                        </div>
                    ` : ''}
                    ${step.error_message ? `
                        <div class="step-error">エラー: ${escapeHtmlGlobal(step.error_message)}</div>
                    ` : ''}
                </div>
            `;
        }
        html += '</div>';
    }

    // Display execution trace (control flow visibility)
    if (job.merged_output && job.merged_output._execution_trace && job.merged_output._execution_trace.length > 0) {
        html += `
            <div class="workflow-execution-trace">
                <h5>実行トレース / Execution Trace</h5>
                <div class="execution-trace-list">
        `;

        for (const trace of job.merged_output._execution_trace) {
            const stepTypeIcon = getStepTypeIcon(trace.step_type);
            const actionClass = getActionClass(trace.action);
            const actionLabel = getActionLabel(trace.action);
            let detailsHtml = '';

            if (trace.step_type === 'set' && trace.assignments) {
                const assignList = Object.entries(trace.assignments)
                    .map(([k, v]) => `${k}=${JSON.stringify(v)}`)
                    .join(', ');
                detailsHtml = `<span class="trace-details">${escapeHtmlGlobal(assignList)}</span>`;
            } else if (trace.step_type === 'if' || trace.step_type === 'elif' || trace.step_type === 'loop') {
                if (trace.condition) {
                    detailsHtml = `<span class="trace-condition">${escapeHtmlGlobal(trace.condition)}</span>`;
                }
                if (trace.iteration !== undefined) {
                    detailsHtml += `<span class="trace-iteration">iteration: ${trace.iteration}</span>`;
                }
            } else if (trace.step_type === 'foreach') {
                if (trace.total_items !== undefined) {
                    detailsHtml = `<span class="trace-details">${trace.item_var}: ${escapeHtmlGlobal(JSON.stringify(trace.current_item))} (${trace.total_items} items)</span>`;
                }
            } else if (trace.step_type === 'endforeach') {
                if (trace.current_item !== undefined) {
                    detailsHtml = `<span class="trace-details">item: ${escapeHtmlGlobal(JSON.stringify(trace.current_item))}</span>`;
                } else if (trace.iterations_completed !== undefined) {
                    detailsHtml = `<span class="trace-details">${trace.iterations_completed} iterations completed</span>`;
                }
            } else if (trace.prompt_name) {
                detailsHtml = `<span class="trace-details">${escapeHtmlGlobal(trace.prompt_name)}</span>`;
            }

            html += `
                <div class="trace-item ${actionClass}">
                    <span class="trace-step-order">[${trace.step_order}]</span>
                    <span class="trace-icon">${stepTypeIcon}</span>
                    <span class="trace-step-type">${trace.step_type.toUpperCase()}</span>
                    <span class="trace-step-name">(${escapeHtmlGlobal(trace.step_name)})</span>
                    <span class="trace-action">${actionLabel}</span>
                    ${detailsHtml}
                </div>
            `;
        }

        html += `
                </div>
            </div>
        `;
    }

    // Display merged output
    if (job.merged_output) {
        // Remove _execution_trace from display to avoid duplication
        const displayOutput = {...job.merged_output};
        delete displayOutput._execution_trace;

        html += `
            <div class="workflow-merged-output">
                <h5>統合結果 / Merged Output</h5>
                <pre>${escapeHtmlGlobal(JSON.stringify(displayOutput, null, 2))}</pre>
            </div>
        `;
    }

    // Display merged CSV output if present
    if (job.merged_csv_output) {
        html += `
            <div class="workflow-csv-output">
                <h5>
                    CSV出力 / CSV Output
                    <button type="button" class="btn-copy-csv" onclick="copyWorkflowCsv('${job.id}')" title="コピー / Copy">📋</button>
                </h5>
                <textarea id="workflow-csv-${job.id}" class="csv-output-area" readonly>${escapeHtmlGlobal(job.merged_csv_output)}</textarea>
            </div>
        `;
    }

    html += '</div>';
    container.innerHTML = html;
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

    // Always remove existing "Load more" link first when appending
    if (append) {
        const existingLoadMore = container.querySelector('.load-more-link');
        if (existingLoadMore) {
            existingLoadMore.remove();
        }
    }

    // Handle empty jobs
    if (!jobs || jobs.length === 0) {
        if (!append) {
            container.innerHTML = '<p class="info">履歴がありません / No history</p>';
        }
        // When append mode with no new items, just update Load More button state
        // (already removed above, add back only if hasMore is still true)
        if (append && singleHistoryHasMore) {
            container.insertAdjacentHTML('beforeend', `
                <div class="load-more-link" onclick="loadMoreSingleHistory()">
                    さらに表示 / Load more...
                </div>
            `);
        }
        return;
    }

    const jobsHtml = jobs.map(job => {
        const createdAt = formatJST(job.created_at);
        const finishedAt = formatJST(job.finished_at);
        const turnaround = job.turnaround_ms ? `${(job.turnaround_ms / 1000).toFixed(1)}s` : 'N/A';
        const itemCount = job.items ? job.items.length : 0;
        const modelName = job.model_name || '-';
        const promptName = job.prompt_name || '-';

        // Show delete button for pending/running jobs
        const canDelete = job.status === 'pending' || job.status === 'running';
        const deleteBtn = canDelete ?
            `<button class="delete-job-btn" onclick="event.stopPropagation(); deleteJob(${job.id}, 'single')" title="ジョブを削除">🗑️</button>` : '';

        return `
            <div class="history-item" data-job-id="${job.id}" onclick="selectHistoryItem(${job.id})">
                <div class="job-header">
                    <div class="job-id">Job #${job.id} (${itemCount} items)</div>
                    ${deleteBtn}
                </div>
                <div class="prompt-info">🎯 ${promptName}</div>
                <div class="timestamp">実行: ${createdAt}</div>
                <div class="timestamp">完了: ${finishedAt}</div>
                <div class="turnaround">モデル: ${modelName} | 実行時間: ${turnaround}</div>
                <span class="status ${job.status}">${job.status}</span>
            </div>
        `;
    }).join('');

    // Add "Load more" link if there are more jobs
    const loadMoreHtml = singleHistoryHasMore ? `
        <div class="load-more-link" onclick="loadMoreSingleHistory()">
            さらに表示 / Load more...
        </div>
    ` : '';

    if (append) {
        container.insertAdjacentHTML('beforeend', jobsHtml + loadMoreHtml);
    } else {
        container.innerHTML = jobsHtml + loadMoreHtml;
    }
}

let singleHistoryLoading = false;

async function loadMoreSingleHistory() {
    // Prevent duplicate clicks while loading
    if (singleHistoryLoading) return;
    singleHistoryLoading = true;

    // Update button to show loading state
    const loadMoreBtn = document.querySelector('#history-list .load-more-link');
    if (loadMoreBtn) {
        loadMoreBtn.textContent = '読み込み中... / Loading...';
        loadMoreBtn.style.pointerEvents = 'none';
    }

    try {
        const pid = currentProjectId || 1;

        // Fetch next page of single-type jobs
        const response = await fetch(`/api/projects/${pid}/jobs?limit=${SINGLE_HISTORY_PAGE_SIZE}&offset=${singleHistoryOffset}&job_type=single`);
        if (!response.ok) throw new Error('Failed to load more jobs');
        const singleJobs = await response.json();

        // Update pagination state BEFORE rendering
        // No more items if we got fewer than requested
        singleHistoryHasMore = singleJobs.length >= SINGLE_HISTORY_PAGE_SIZE;
        singleHistoryOffset += singleJobs.length;

        // Append to existing history (or update Load More button state)
        renderHistory(singleJobs, true);
    } catch (error) {
        showStatus('履歴の読み込みに失敗しました / Failed to load more history', 'error');
    } finally {
        singleHistoryLoading = false;
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

    // Safely access recent_jobs with null check
    const recentJobs = currentConfig?.recent_jobs || [];
    const job = recentJobs.find(j => j.id === jobId);
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

    // Display merged CSV output for batch jobs, repeated single executions, and single with header
    let mergedCsvSection = '';
    if (job.merged_csv_output) {
        // Store CSV content in global storage to avoid escaping issues
        storeCsvContent(job.id, job.merged_csv_output);
        const isBatch = job.job_type === 'batch';
        const itemCount = job.items ? job.items.length : 0;
        let title;
        if (isBatch) {
            title = 'バッチ実行結果 (CSV統合) / Batch Results (Merged CSV)';
        } else if (itemCount > 1) {
            title = 'n回送信結果 (CSV統合) / Repeated Execution Results (Merged CSV)';
        } else {
            title = 'パーサー結果 (CSV) / Parsed Results (CSV)';
        }
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
    console.log('🚀 executePrompt called with repeat:', repeat);
    console.log('📋 currentParameters:', currentParameters);
    console.log('📂 currentProjectId:', currentProjectId);
    console.log('🎯 currentSelectionType:', currentSelectionType);

    const inputParams = {};
    let valid = true;

    // Process parameters (including FILE type)
    for (const param of currentParameters) {
        const input = document.getElementById(`param-${param.name}`);

        if (param.html_type === 'file') {
            // Handle FILE type - convert to Base64
            const hasFile = input && input.files && input.files.length > 0;

            // Check if required parameter has file
            if (param.required && !hasFile) {
                valid = false;
                showStatus(`ファイル "${param.name}" を選択してください`, 'error');
                break;
            }

            // Process file if provided
            if (hasFile) {
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
            }
        } else {
            // Handle other types (text, number, date, FILEPATH, etc.)
            const value = input ? input.value.trim() : '';

            // Check if required parameter has value
            if (param.required && !value) {
                valid = false;
                showStatus(`パラメータ "${param.name}" を入力してください`, 'error');
                break;
            }

            // Only include in params if there's a value (or if required)
            if (value || param.required) {
                inputParams[param.name] = input ? input.value : '';
            }
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

        // Check if we're executing a workflow, prompt, or project
        if (currentSelectionType === 'workflow' && currentWorkflowId) {
            // Workflow execution
            await executeWorkflow(inputParams, modelName, modelParams.temperature || 0.7, repeat);
        } else {
            // Regular prompt/project execution
            const requestBody = {
                project_id: currentProjectId || 1,
                input_params: inputParams,
                repeat: repeat,
                model_name: modelName,
                include_csv_header: includeCsvHeader,
                ...modelParams  // Include all model parameters from system settings
            };

            // NEW ARCHITECTURE: Add prompt_id if executing a specific prompt
            if (currentSelectionType === 'prompt' && currentPromptId) {
                requestBody.prompt_id = currentPromptId;
            }

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
        }
    } catch (error) {
        showStatus(`エラー / Error: ${error.message}`, 'error');
        setExecutionState(false);
        // Hide stop button on error
        document.getElementById('btn-stop-single').style.display = 'none';
        currentSingleJobId = null;
    }
}

/**
 * Execute workflow
 * @param {Object} inputParams - Input parameters
 * @param {string} modelName - Model name
 * @param {number} temperature - Temperature setting
 * @param {number} repeat - Number of times to repeat (for workflows, execute sequentially)
 */
async function executeWorkflow(inputParams, modelName, temperature, repeat) {
    console.log(`🔄 Executing workflow ${currentWorkflowId} with repeat=${repeat}`);

    for (let i = 0; i < repeat; i++) {
        if (repeat > 1) {
            showStatus(`ワークフロー実行中... (${i + 1}/${repeat})`, 'info');
        }

        const requestBody = {
            input_params: inputParams,
            model_name: modelName,
            temperature: temperature
        };

        console.log(`🚀 Sending request to /api/workflows/${currentWorkflowId}/run`);

        const response = await fetch(`/api/workflows/${currentWorkflowId}/run`, {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify(requestBody)
        });

        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.detail || 'Workflow execution failed');
        }

        const result = await response.json();
        console.log('📥 Workflow job created:', result);

        // Start polling for workflow job progress
        pollWorkflowJobProgress(result.id, currentWorkflowId);

        // If this is not the last iteration, wait a bit before the next one
        if (i < repeat - 1) {
            await new Promise(resolve => setTimeout(resolve, 500));
        }
    }

    showStatus(`ワークフロージョブ開始！`, 'info');
    setExecutionState(false);
}

// Poll workflow job progress until completion
let workflowPollIntervalId = null;

async function pollWorkflowJobProgress(jobId, workflowId) {
    // Clear any existing polling interval
    if (workflowPollIntervalId) {
        clearInterval(workflowPollIntervalId);
    }

    // Poll every 3 seconds
    workflowPollIntervalId = setInterval(async () => {
        try {
            const response = await fetch(`/api/workflow-jobs/${jobId}`);
            if (!response.ok) {
                clearInterval(workflowPollIntervalId);
                workflowPollIntervalId = null;
                hideSingleStopButton();
                return;
            }

            const job = await response.json();

            // Update display with latest job data
            displayWorkflowJobResults(job);

            // If job is complete or error, stop polling
            if (job.status === 'done' || job.status === 'completed' || job.status === 'error') {
                clearInterval(workflowPollIntervalId);
                workflowPollIntervalId = null;
                hideSingleStopButton();

                if (job.status === 'done' || job.status === 'completed') {
                    showStatus('ワークフロー完了！', 'success');
                } else {
                    showStatus('ワークフローでエラーが発生しました', 'error');
                }

                // Refresh workflow history
                if (currentSelectionType === 'workflow' && currentWorkflowId) {
                    await loadWorkflowConfig(currentWorkflowId);
                }
            }
        } catch (error) {
            console.error('Failed to poll workflow job:', error);
            clearInterval(workflowPollIntervalId);
            workflowPollIntervalId = null;
            hideSingleStopButton();
        }
    }, 3000);
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

            // Check if job is complete (including cancelled)
            const isComplete = job.status === 'done' || job.status === 'error' || job.status === 'cancelled';
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

                // Reload history to show final status (use new architecture)
                if (currentProjectId) {
                    await loadExecutionTargets(currentProjectId);
                } else {
                    await loadConfig();
                }
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
    console.log(`📢 showStatus: "${message}" (${type})`);
    const statusDiv = document.getElementById('execution-status');
    if (!statusDiv) {
        console.error('❌ execution-status element not found!');
        return;
    }

    statusDiv.textContent = message;
    statusDiv.className = `status-message ${type} show`;
    console.log('✅ Status displayed, className:', statusDiv.className);

    if (type === 'success') {
        setTimeout(() => statusDiv.classList.remove('show'), 5000);
    }
}

async function onProjectChange(e) {
    // Handle both event-triggered and manual calls
    let selectValue;
    if (e && e.target) {
        selectValue = e.target.value;
    } else {
        // Manual call - get from dropdown
        const singleSelect = document.getElementById('single-project-select');
        if (singleSelect) {
            selectValue = singleSelect.value;
        }
    }

    // Parse the select value to determine type
    const { type, id } = parseSelectValue(selectValue);

    if (type === 'workflow') {
        currentSelectionType = 'workflow';
        currentWorkflowId = id;
        currentProjectId = null;
        currentPromptId = null;
        await loadWorkflowConfig(id);
    } else {
        currentSelectionType = 'project';
        currentProjectId = id;
        currentWorkflowId = null;
        currentPromptId = null;

        // NEW ARCHITECTURE: Load execution targets (prompts and workflows) for this project
        await loadExecutionTargets(id);
    }
}

/**
 * NEW ARCHITECTURE: Load execution targets (prompts and workflows) for a project
 * This populates the second dropdown with prompts and workflows
 */
async function loadExecutionTargets(projectId) {
    try {
        const response = await fetch(`/api/projects/${projectId}/execution-targets`);
        if (!response.ok) {
            throw new Error('Failed to load execution targets');
        }

        currentExecutionTargets = await response.json();

        // Update the execution target selector
        updateExecutionTargetSelector(currentExecutionTargets);

        // Also load and display history for this project
        singleHistoryOffset = 0;
        singleHistoryHasMore = true;
        const jobsResponse = await fetch(`/api/projects/${projectId}/jobs?limit=${SINGLE_HISTORY_PAGE_SIZE}&offset=0&job_type=single`);
        if (jobsResponse.ok) {
            const singleJobs = await jobsResponse.json();
            singleHistoryHasMore = singleJobs.length >= SINGLE_HISTORY_PAGE_SIZE;
            singleHistoryOffset = singleJobs.length;
            renderHistory(singleJobs);
        }

        // Auto-select first prompt if available
        if (currentExecutionTargets.prompts && currentExecutionTargets.prompts.length > 0) {
            const firstPrompt = currentExecutionTargets.prompts[0];
            currentPromptId = firstPrompt.id;
            currentSelectionType = 'prompt';

            // Update selector value
            const targetSelect = document.getElementById('single-target-select');
            if (targetSelect) {
                targetSelect.value = `prompt:${firstPrompt.id}`;
            }

            // Load config for the first prompt
            await loadPromptConfig(firstPrompt);
        } else {
            // Fallback to old behavior if no prompts
            await loadConfig();
        }
    } catch (error) {
        console.error('Failed to load execution targets:', error);
        // Fallback to old behavior
        await loadConfig();
    }
}

/**
 * NEW ARCHITECTURE: Update the execution target selector dropdown
 */
function updateExecutionTargetSelector(targets) {
    const targetSelect = document.getElementById('single-target-select');
    if (!targetSelect) {
        console.log('Target selector not found, skipping update');
        return;
    }

    let options = '';

    // Add prompts
    if (targets.prompts && targets.prompts.length > 0) {
        options += '<optgroup label="プロンプト / Prompts">';
        targets.prompts.forEach(prompt => {
            options += `<option value="prompt:${prompt.id}">${prompt.name}</option>`;
        });
        options += '</optgroup>';
    }

    // Add workflows
    if (targets.workflows && targets.workflows.length > 0) {
        options += '<optgroup label="ワークフロー / Workflows">';
        targets.workflows.forEach(workflow => {
            options += `<option value="workflow:${workflow.id}">${workflow.name} (${workflow.step_count} steps)</option>`;
        });
        options += '</optgroup>';
    }

    targetSelect.innerHTML = options;
    targetSelect.style.display = options ? 'block' : 'none';
}

/**
 * Refresh the single execution targets dropdown (prompts and workflows) without changing selection
 * Called after creating, cloning, or deleting workflows
 */
async function refreshSingleExecutionTargets() {
    if (!currentProjectId) return;

    try {
        const response = await fetch(`/api/projects/${currentProjectId}/execution-targets`);
        if (!response.ok) return;

        const targets = await response.json();
        currentExecutionTargets = targets;

        // Remember current selection
        const targetSelect = document.getElementById('single-target-select');
        const currentValue = targetSelect ? targetSelect.value : null;

        // Update the dropdown
        updateExecutionTargetSelector(targets);

        // Restore selection if it still exists
        if (currentValue && targetSelect) {
            const optionExists = Array.from(targetSelect.options).some(opt => opt.value === currentValue);
            if (optionExists) {
                targetSelect.value = currentValue;
            }
        }
    } catch (error) {
        console.error('Error refreshing execution targets:', error);
    }
}

/**
 * NEW ARCHITECTURE: Handle execution target selection (prompt or workflow within a project)
 */
async function onExecutionTargetChange(e) {
    const value = e.target.value;
    const [type, id] = value.split(':');

    if (type === 'workflow') {
        currentSelectionType = 'workflow';
        currentWorkflowId = parseInt(id);
        currentPromptId = null;
        await loadWorkflowConfig(currentWorkflowId);
    } else if (type === 'prompt') {
        currentSelectionType = 'prompt';
        currentPromptId = parseInt(id);
        currentWorkflowId = null;

        // Always fetch fresh prompt data from API to ensure we have latest parameters
        try {
            const response = await fetch(`/api/prompts/${currentPromptId}`);
            if (response.ok) {
                const prompt = await response.json();
                await loadPromptConfig(prompt);

                // Also update the cached version in currentExecutionTargets
                if (currentExecutionTargets?.prompts) {
                    const index = currentExecutionTargets.prompts.findIndex(p => p.id === currentPromptId);
                    if (index !== -1) {
                        currentExecutionTargets.prompts[index] = prompt;
                    }
                }
            } else {
                showStatus('プロンプトの読み込みに失敗しました', 'error');
            }
        } catch (error) {
            console.error('Failed to fetch prompt:', error);
            showStatus(`プロンプト読み込みエラー: ${error.message}`, 'error');
        }
    }
}

/**
 * NEW ARCHITECTURE: Load configuration for a specific prompt
 */
async function loadPromptConfig(prompt) {
    try {
        // Preserve existing recent_jobs when updating config
        const existingJobs = currentConfig?.recent_jobs || [];

        // Update current config from prompt data
        currentConfig = {
            prompt_template: prompt.prompt_template,
            parser_config: prompt.parser_config,
            parameters: prompt.parameters,
            recent_jobs: existingJobs  // Preserve history
        };

        currentParameters = prompt.parameters || [];

        // Update prompt template display
        const templateDisplay = document.getElementById('prompt-template');
        if (templateDisplay) {
            templateDisplay.textContent = prompt.prompt_template || '';
        }

        // Render parameter inputs
        renderParameterInputs();

        showStatus(`プロンプト "${prompt.name}" を読み込みました`, 'success');
    } catch (error) {
        showStatus(`プロンプト読み込みエラー: ${error.message}`, 'error');
    }
}

/**
 * NEW ARCHITECTURE: Show add prompt modal
 */
async function showAddPromptModal() {
    if (!currentProjectId) {
        alert('プロジェクトを選択してください / Please select a project');
        return;
    }

    const modalContent = `
        <div class="modal-header">
            新規プロンプト作成 / Create New Prompt
        </div>
        <div class="modal-body">
            <div class="form-group">
                <label>プロンプト名 / Prompt Name:</label>
                <input type="text" id="new-prompt-name" style="width: 100%; padding: 0.5rem; box-sizing: border-box;" placeholder="例: 要約プロンプト">
            </div>
            <div class="form-group">
                <label>説明 / Description:</label>
                <input type="text" id="new-prompt-description" style="width: 100%; padding: 0.5rem; box-sizing: border-box;" placeholder="例: テキストを要約するプロンプト">
            </div>
            <div class="form-group">
                <label>プロンプトテンプレート / Prompt Template:</label>
                <textarea id="new-prompt-template" rows="10" style="font-family: 'Courier New', monospace; width: 100%; box-sizing: border-box;">以下の指示に従って回答してください。

{{INPUT:TEXT10}}

回答:</textarea>
            </div>
        </div>
        <div class="modal-footer">
            <button class="btn btn-secondary" onclick="closeModal()">キャンセル / Cancel</button>
            <button class="btn btn-primary" onclick="createNewPrompt()">作成 / Create</button>
        </div>
    `;
    showModal(modalContent);
}

/**
 * NEW ARCHITECTURE: Create new prompt
 */
async function createNewPrompt() {
    const name = document.getElementById('new-prompt-name').value.trim();
    const description = document.getElementById('new-prompt-description').value.trim();
    const template = document.getElementById('new-prompt-template').value;

    if (!name) {
        alert('プロンプト名を入力してください / Please enter a prompt name');
        return;
    }

    try {
        const response = await fetch(`/api/projects/${currentProjectId}/prompts`, {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({
                name: name,
                description: description,
                prompt_template: template
            })
        });

        if (!response.ok) throw new Error('Failed to create prompt');

        const newPrompt = await response.json();
        closeModal();

        // Reload execution targets and select the new prompt
        await loadExecutionTargets(currentProjectId);

        // Select the newly created prompt
        const targetSelect = document.getElementById('single-target-select');
        if (targetSelect) {
            targetSelect.value = `prompt:${newPrompt.id}`;
            currentPromptId = newPrompt.id;
            currentSelectionType = 'prompt';
            await loadPromptConfig(newPrompt);
        }

        showStatus(`プロンプト「${name}」を作成しました / Created prompt "${name}"`, 'success');
    } catch (error) {
        alert(`エラー / Error: ${error.message}`);
    }
}

/**
 * NEW ARCHITECTURE: Delete current prompt
 */
async function deleteCurrentPrompt() {
    if (!currentPromptId) {
        alert('削除するプロンプトを選択してください / Please select a prompt to delete');
        return;
    }

    // Find prompt name from currentExecutionTargets
    const prompt = currentExecutionTargets?.prompts?.find(p => p.id === currentPromptId);
    const promptName = prompt ? prompt.name : `ID: ${currentPromptId}`;

    if (!confirm(`プロンプト「${promptName}」を削除しますか？\nこの操作は取り消せません。\n\nDelete prompt "${promptName}"?\nThis action cannot be undone.`)) {
        return;
    }

    try {
        const response = await fetch(`/api/prompts/${currentPromptId}`, {
            method: 'DELETE'
        });

        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.detail || 'Failed to delete prompt');
        }

        // Close modal if open
        closeModal();

        showStatus(`プロンプト「${promptName}」を削除しました / Deleted prompt "${promptName}"`, 'success');

        // Reload execution targets (will auto-select first prompt)
        currentPromptId = null;
        await loadExecutionTargets(currentProjectId);

    } catch (error) {
        alert(`エラー / Error: ${error.message}`);
    }
}

/**
 * Show edit prompt modal
 * NEW ARCHITECTURE: Uses PromptRevision instead of ProjectRevision
 * Specification: docs/req.txt section 4.4.3 (Revision Management)
 */
async function showEditPromptModal() {
    // Use the unified draggable prompt editor window
    if (!currentProjectId) {
        alert('プロジェクトを選択してください / Please select a project');
        return;
    }

    // Open the unified prompt editor window
    await openPromptEditorWindow(currentProjectId, currentPromptId, null);
}

/**
 * NEW ARCHITECTURE: Unified Prompt Management Modal
 * Features:
 * - Prompt selector dropdown to switch between prompts
 * - Tab interface for Prompt Template / Parser Config
 * - Create/Delete buttons
 * - Revision selector with restore
 */
let currentModalTab = 'prompt';  // 'prompt' or 'parser'
let currentModalPromptId = null;
let currentModalPromptData = null;
let currentModalRevisions = [];

async function showPromptManagementModal(initialTab = 'prompt') {
    if (!currentProjectId) {
        alert('プロジェクトを選択してください / Please select a project');
        return;
    }

    currentModalTab = initialTab;
    currentModalPromptId = currentPromptId;

    try {
        // Load all prompts for this project
        const targetsResponse = await fetch(`/api/projects/${currentProjectId}/execution-targets`);
        if (!targetsResponse.ok) throw new Error('Failed to load prompts');
        const targets = await targetsResponse.json();
        const prompts = targets.prompts || [];

        if (prompts.length === 0) {
            alert('プロンプトがありません / No prompts available');
            return;
        }

        // If no prompt selected, use the first one
        if (!currentModalPromptId) {
            currentModalPromptId = prompts[0].id;
        }

        await renderPromptManagementModal(prompts);
    } catch (error) {
        alert(`エラー / Error: ${error.message}`);
    }
}

async function renderPromptManagementModal(prompts) {
    // Load current prompt data and revisions
    const [promptResponse, revisionsResponse] = await Promise.all([
        fetch(`/api/prompts/${currentModalPromptId}`),
        fetch(`/api/prompts/${currentModalPromptId}/revisions`)
    ]);

    if (!promptResponse.ok) throw new Error('Failed to load prompt');
    currentModalPromptData = await promptResponse.json();
    currentModalRevisions = revisionsResponse.ok ? await revisionsResponse.json() : [];

    // Build prompt selector options
    const promptOptions = prompts.map(p =>
        `<option value="${p.id}" ${p.id === currentModalPromptId ? 'selected' : ''}>${p.name}</option>`
    ).join('');

    // Build revision selector options
    const revisionOptions = currentModalRevisions.map(rev => {
        const date = formatJST(rev.created_at);
        const isCurrent = rev.revision === currentModalPromptData.revision_count;
        return `<option value="${rev.revision}" ${isCurrent ? 'selected' : ''}>
            Rev.${rev.revision} (${date})${isCurrent ? ' - 現在' : ''}
        </option>`;
    }).join('');

    // Parse parser config
    let parserConfig = {type: 'none'};
    try {
        if (currentModalPromptData.parser_config) {
            parserConfig = JSON.parse(currentModalPromptData.parser_config);
        }
    } catch (e) { /* ignore */ }

    // Tab content based on current tab
    const promptTabActive = currentModalTab === 'prompt';
    const parserTabActive = currentModalTab === 'parser';

    // Textarea sizing: consistent height across tabs to prevent size change on tab switch
    // Parser tab has extra selector (~70px), so prompt textarea is larger to match total height
    const promptContent = `
        <div class="form-group" style="margin: 0;">
            <label style="display: block; margin-bottom: 5px;">プロンプトテンプレート / Prompt Template:</label>
            <textarea id="edit-prompt-template" style="font-family: 'Courier New', monospace; width: 100%; box-sizing: border-box; height: 550px; max-height: 2000px; resize: vertical;">${currentModalPromptData.prompt_template || ''}</textarea>
        </div>
    `;

    const parserContent = `
        <div class="form-group" style="margin-bottom: 10px;">
            <label>パーサータイプ / Parser Type:</label>
            <select id="edit-parser-type" style="width: 100%; padding: 0.5rem;">
                <option value="none" ${parserConfig.type === 'none' ? 'selected' : ''}>なし / None</option>
                <option value="json" ${parserConfig.type === 'json' ? 'selected' : ''}>JSON (フィールド抽出) / JSON (Field Extract)</option>
                <option value="json_path" ${parserConfig.type === 'json_path' ? 'selected' : ''}>JSON Path</option>
                <option value="regex" ${parserConfig.type === 'regex' ? 'selected' : ''}>正規表現 / Regex</option>
                <option value="csv" ${parserConfig.type === 'csv' ? 'selected' : ''}>CSV</option>
            </select>
        </div>
        <div class="form-group" style="margin: 0;">
            <label style="display: block; margin-bottom: 5px;">パーサー設定 (JSON) / Parser Config:</label>
            <textarea id="edit-parser-config" style="font-family: 'Courier New', monospace; width: 100%; box-sizing: border-box; height: 280px; max-height: 2000px; resize: vertical;">${JSON.stringify(parserConfig, null, 2)}</textarea>
        </div>
        <!-- Inline JSON to CSV Converter -->
        <div id="json-csv-converter-section" style="margin-top: 10px; border: 1px solid #9b59b6; border-radius: 5px; display: none;">
            <div style="background: #9b59b6; color: white; padding: 8px 12px; display: flex; justify-content: space-between; align-items: center;">
                <span style="font-weight: bold;">📊 JSON → CSV 変換</span>
                <button onclick="toggleJsonCsvConverter()" style="background: transparent; border: 1px solid white; color: white; padding: 2px 8px; border-radius: 3px; cursor: pointer; font-size: 0.8rem;">閉じる</button>
            </div>
            <div style="padding: 10px;">
                <div style="display: flex; gap: 10px;">
                    <div style="flex: 1;">
                        <label style="font-size: 0.85rem; font-weight: bold; display: block; margin-bottom: 3px;">サンプルJSON入力:</label>
                        <textarea id="json-sample-input" rows="8" style="font-family: 'Courier New', monospace; width: 100%; font-size: 0.85rem;" placeholder='{"field1": "value", "field2": {"nested": "data"}}'></textarea>
                    </div>
                    <div style="display: flex; flex-direction: column; justify-content: center; gap: 5px;">
                        <button onclick="convertJsonToCsvTemplateInline()" style="background: #9b59b6; color: white; border: none; padding: 8px 12px; border-radius: 3px; cursor: pointer; font-size: 0.85rem;">🔄 変換</button>
                        <button onclick="applyGeneratedParserConfigInline()" style="background: #27ae60; color: white; border: none; padding: 8px 12px; border-radius: 3px; cursor: pointer; font-size: 0.85rem;">✅ 適用</button>
                    </div>
                    <div style="flex: 1;">
                        <label style="font-size: 0.85rem; font-weight: bold; display: block; margin-bottom: 3px;">生成された設定:</label>
                        <textarea id="generated-parser-config-inline" rows="8" style="font-family: 'Courier New', monospace; width: 100%; font-size: 0.85rem; background: #f8f9fa;" readonly placeholder="変換結果がここに表示されます"></textarea>
                    </div>
                </div>
                <div style="margin-top: 5px;">
                    <label style="font-size: 0.85rem; font-weight: bold;">CSVヘッダープレビュー:</label>
                    <input type="text" id="csv-header-preview-inline" readonly style="width: 100%; font-family: 'Courier New', monospace; font-size: 0.85rem; background: #f8f9fa; padding: 4px;" placeholder="ヘッダーがここに表示されます">
                </div>
            </div>
        </div>
    `;

    const modalContent = `
        <div class="modal-header" style="display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 10px;">
            <span style="font-weight: bold; font-size: 1.1rem;">
                プロンプト管理 / Prompt Management
                <button onclick="showUnifiedHelp()" style="background: none; border: none; cursor: pointer; font-size: 1rem; margin-left: 5px;" title="ヘルプ / Help">❓</button>
            </span>
            <button class="btn btn-success" onclick="showAddPromptModalFromManagement()" style="font-size: 0.85rem;" title="新規プロンプト作成 / Create new prompt">
                ＋ 新規作成 / New
            </button>
        </div>
        <div class="modal-body" style="overflow-y: auto;">
            <!-- Prompt Selector -->
            <div class="form-group" style="display: flex; align-items: center; gap: 10px; margin-bottom: 10px;">
                <label style="margin: 0; white-space: nowrap;">プロンプト / Prompt:</label>
                <select id="modal-prompt-selector" onchange="onModalPromptChange(this.value)" style="flex: 1; padding: 0.4rem;">
                    ${promptOptions}
                </select>
                <button class="btn btn-danger" onclick="deletePromptFromModal()" style="font-size: 0.85rem;" title="削除 / Delete">
                    🗑
                </button>
            </div>

            <!-- Prompt Metadata Editing -->
            <div style="display: flex; gap: 10px; margin-bottom: 10px; padding-bottom: 10px; border-bottom: 1px solid #ddd;">
                <div style="flex: 1;">
                    <label style="font-size: 0.85rem; display: block; margin-bottom: 3px;">プロンプト名 / Name:</label>
                    <input type="text" id="modal-prompt-name" value="${currentModalPromptData.name || ''}"
                           style="width: 100%; padding: 0.4rem; border: 1px solid #ccc; border-radius: 4px; box-sizing: border-box;"
                           placeholder="プロンプト名を入力">
                </div>
                <div style="flex: 2;">
                    <label style="font-size: 0.85rem; display: block; margin-bottom: 3px;">説明 / Description:</label>
                    <input type="text" id="modal-prompt-description" value="${currentModalPromptData.description || ''}"
                           style="width: 100%; padding: 0.4rem; border: 1px solid #ccc; border-radius: 4px; box-sizing: border-box;"
                           placeholder="プロンプトの説明（任意）">
                </div>
            </div>

            <!-- Tab Navigation -->
            <div style="display: flex; gap: 0; margin-bottom: 10px; border-bottom: 2px solid #007bff;">
                <button id="tab-btn-prompt" onclick="switchModalTab('prompt')"
                    style="padding: 8px 20px; border: none; background: ${promptTabActive ? '#007bff' : '#e9ecef'}; color: ${promptTabActive ? 'white' : '#333'}; cursor: pointer; border-radius: 5px 5px 0 0; font-weight: ${promptTabActive ? 'bold' : 'normal'};">
                    プロンプト / Prompt
                </button>
                <button id="tab-btn-parser" onclick="switchModalTab('parser')"
                    style="padding: 8px 20px; border: none; background: ${parserTabActive ? '#007bff' : '#e9ecef'}; color: ${parserTabActive ? 'white' : '#333'}; cursor: pointer; border-radius: 5px 5px 0 0; font-weight: ${parserTabActive ? 'bold' : 'normal'};">
                    パーサー / Parser
                </button>
            </div>

            <!-- Revision Selector -->
            <div class="form-group" style="display: flex; align-items: center; gap: 10px; margin-bottom: 10px;">
                <label style="margin: 0; white-space: nowrap;">リビジョン / Rev:</label>
                <select id="revision-selector" onchange="loadModalRevisionContent(this.value)" style="flex: 1; padding: 0.4rem;">
                    ${revisionOptions}
                </select>
                <button class="btn btn-secondary" onclick="restoreModalRevision()" style="background-color: #e67e22; font-size: 0.85rem;" title="復元 / Restore">
                    🔄 復元
                </button>
            </div>

            <!-- Tab Content - no height restriction, textarea can grow freely -->
            <div id="modal-tab-content">
                ${promptTabActive ? promptContent : parserContent}
            </div>
        </div>
        <div class="modal-footer" style="display: flex; justify-content: space-between; flex-wrap: wrap; gap: 0.5rem;">
            <div>
                ${parserTabActive ? '<button id="json-csv-toggle-btn" onclick="toggleJsonCsvConverter()" style="font-size: 0.8rem; padding: 4px 10px; background: transparent; border: 1px solid #9b59b6; color: #9b59b6; border-radius: 3px; cursor: pointer;">JSON→CSV</button>' : ''}
            </div>
            <div style="display: flex; gap: 0.5rem;">
                <button class="btn btn-secondary" onclick="closeModal()">キャンセル / Cancel</button>
                <button class="btn btn-primary" onclick="saveModalContent()">保存 / Save</button>
            </div>
        </div>
    `;
    showModal(modalContent);
}

async function onModalPromptChange(promptId) {
    currentModalPromptId = parseInt(promptId);
    // Reload modal with new prompt
    const targetsResponse = await fetch(`/api/projects/${currentProjectId}/execution-targets`);
    if (targetsResponse.ok) {
        const targets = await targetsResponse.json();
        await renderPromptManagementModal(targets.prompts || []);
    }
}

function switchModalTab(tab) {
    currentModalTab = tab;

    // Update tab button styles
    const promptBtn = document.getElementById('tab-btn-prompt');
    const parserBtn = document.getElementById('tab-btn-parser');

    if (tab === 'prompt') {
        promptBtn.style.background = '#007bff';
        promptBtn.style.color = 'white';
        promptBtn.style.fontWeight = 'bold';
        parserBtn.style.background = '#e9ecef';
        parserBtn.style.color = '#333';
        parserBtn.style.fontWeight = 'normal';
    } else {
        parserBtn.style.background = '#007bff';
        parserBtn.style.color = 'white';
        parserBtn.style.fontWeight = 'bold';
        promptBtn.style.background = '#e9ecef';
        promptBtn.style.color = '#333';
        promptBtn.style.fontWeight = 'normal';
    }

    // Update footer button visibility
    const footerLeftDiv = document.querySelector('.modal-footer > div:first-child');
    if (footerLeftDiv) {
        if (tab === 'parser') {
            footerLeftDiv.innerHTML = '<button id="json-csv-toggle-btn" onclick="toggleJsonCsvConverter()" style="font-size: 0.8rem; padding: 4px 10px; background: transparent; border: 1px solid #9b59b6; color: #9b59b6; border-radius: 3px; cursor: pointer;">JSON→CSV</button>';
        } else {
            footerLeftDiv.innerHTML = '';
        }
    }

    // Update tab content - consistent height across tabs
    const contentDiv = document.getElementById('modal-tab-content');
    if (tab === 'prompt') {
        contentDiv.innerHTML = `
            <div class="form-group" style="margin: 0;">
                <label style="display: block; margin-bottom: 5px;">プロンプトテンプレート / Prompt Template:</label>
                <textarea id="edit-prompt-template" style="font-family: 'Courier New', monospace; width: 100%; box-sizing: border-box; height: 550px; max-height: 2000px; resize: vertical;">${currentModalPromptData.prompt_template || ''}</textarea>
            </div>
        `;
    } else {
        let parserConfig = {type: 'none'};
        try {
            if (currentModalPromptData.parser_config) {
                parserConfig = JSON.parse(currentModalPromptData.parser_config);
            }
        } catch (e) { /* ignore */ }

        contentDiv.innerHTML = `
            <div class="form-group" style="margin-bottom: 10px;">
                <label>パーサータイプ / Parser Type:</label>
                <select id="edit-parser-type" style="width: 100%; padding: 0.5rem;">
                    <option value="none" ${parserConfig.type === 'none' ? 'selected' : ''}>なし / None</option>
                    <option value="json" ${parserConfig.type === 'json' ? 'selected' : ''}>JSON (フィールド抽出)</option>
                    <option value="json_path" ${parserConfig.type === 'json_path' ? 'selected' : ''}>JSON Path</option>
                    <option value="regex" ${parserConfig.type === 'regex' ? 'selected' : ''}>正規表現 / Regex</option>
                    <option value="csv" ${parserConfig.type === 'csv' ? 'selected' : ''}>CSV</option>
                </select>
            </div>
            <div class="form-group" style="margin: 0;">
                <label style="display: block; margin-bottom: 5px;">パーサー設定 (JSON) / Parser Config:</label>
                <textarea id="edit-parser-config" style="font-family: 'Courier New', monospace; width: 100%; box-sizing: border-box; height: 280px; max-height: 2000px; resize: vertical;">${JSON.stringify(parserConfig, null, 2)}</textarea>
            </div>
            <!-- Inline JSON to CSV Converter -->
            <div id="json-csv-converter-section" style="margin-top: 10px; border: 1px solid #9b59b6; border-radius: 5px; display: none;">
                <div style="background: #9b59b6; color: white; padding: 8px 12px; display: flex; justify-content: space-between; align-items: center;">
                    <span style="font-weight: bold;">📊 JSON → CSV 変換</span>
                    <button onclick="toggleJsonCsvConverter()" style="background: transparent; border: 1px solid white; color: white; padding: 2px 8px; border-radius: 3px; cursor: pointer; font-size: 0.8rem;">閉じる</button>
                </div>
                <div style="padding: 10px;">
                    <div style="display: flex; gap: 10px;">
                        <div style="flex: 1;">
                            <label style="font-size: 0.85rem; font-weight: bold; display: block; margin-bottom: 3px;">サンプルJSON入力:</label>
                            <textarea id="json-sample-input" rows="8" style="font-family: 'Courier New', monospace; width: 100%; font-size: 0.85rem;" placeholder='{"field1": "value", "field2": {"nested": "data"}}'></textarea>
                        </div>
                        <div style="display: flex; flex-direction: column; justify-content: center; gap: 5px;">
                            <button onclick="convertJsonToCsvTemplateInline()" style="background: #9b59b6; color: white; border: none; padding: 8px 12px; border-radius: 3px; cursor: pointer; font-size: 0.85rem;">🔄 変換</button>
                            <button onclick="applyGeneratedParserConfigInline()" style="background: #27ae60; color: white; border: none; padding: 8px 12px; border-radius: 3px; cursor: pointer; font-size: 0.85rem;">✅ 適用</button>
                        </div>
                        <div style="flex: 1;">
                            <label style="font-size: 0.85rem; font-weight: bold; display: block; margin-bottom: 3px;">生成された設定:</label>
                            <textarea id="generated-parser-config-inline" rows="8" style="font-family: 'Courier New', monospace; width: 100%; font-size: 0.85rem; background: #f8f9fa;" readonly placeholder="変換結果がここに表示されます"></textarea>
                        </div>
                    </div>
                    <div style="margin-top: 5px;">
                        <label style="font-size: 0.85rem; font-weight: bold;">CSVヘッダープレビュー:</label>
                        <input type="text" id="csv-header-preview-inline" readonly style="width: 100%; font-family: 'Courier New', monospace; font-size: 0.85rem; background: #f8f9fa; padding: 4px;" placeholder="ヘッダーがここに表示されます">
                    </div>
                </div>
            </div>
        `;
    }
}

async function loadModalRevisionContent(revisionNumber) {
    const revision = currentModalRevisions.find(r => r.revision === parseInt(revisionNumber));
    if (!revision) return;

    if (currentModalTab === 'prompt') {
        document.getElementById('edit-prompt-template').value = revision.prompt_template || '';
    } else {
        let parserConfig = {type: 'none'};
        try {
            if (revision.parser_config) {
                parserConfig = JSON.parse(revision.parser_config);
            }
        } catch (e) { /* ignore */ }
        document.getElementById('edit-parser-type').value = parserConfig.type || 'none';
        document.getElementById('edit-parser-config').value = JSON.stringify(parserConfig, null, 2);
    }
}

async function restoreModalRevision() {
    const selector = document.getElementById('revision-selector');
    if (!selector) return;

    const revisionNumber = parseInt(selector.value);
    const selectedOption = selector.options[selector.selectedIndex];
    const isCurrent = selectedOption.text.includes('現在');

    if (isCurrent) {
        alert('現在のリビジョンは復元できません\nCannot restore current revision');
        return;
    }

    if (!confirm(`リビジョン ${revisionNumber} を復元しますか？\nRestore revision ${revisionNumber}?`)) {
        return;
    }

    try {
        const response = await fetch(`/api/prompts/${currentModalPromptId}/revisions/${revisionNumber}/restore`, {
            method: 'POST'
        });

        if (!response.ok) throw new Error('Failed to restore revision');

        const result = await response.json();
        showStatus(`リビジョン ${revisionNumber} を復元しました (Rev.${result.revision})`, 'success');

        // Reload modal
        const targetsResponse = await fetch(`/api/projects/${currentProjectId}/execution-targets`);
        if (targetsResponse.ok) {
            const targets = await targetsResponse.json();
            await renderPromptManagementModal(targets.prompts || []);
        }
    } catch (error) {
        alert(`エラー / Error: ${error.message}`);
    }
}

async function saveModalContent() {
    try {
        // Save metadata (name, description) first
        const promptName = document.getElementById('modal-prompt-name')?.value?.trim();
        const promptDescription = document.getElementById('modal-prompt-description')?.value?.trim() || '';

        if (!promptName) {
            alert('プロンプト名を入力してください / Please enter a prompt name');
            return;
        }

        const metadataResponse = await fetch(`/api/prompts/${currentModalPromptId}`, {
            method: 'PUT',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({
                name: promptName,
                description: promptDescription
            })
        });

        if (!metadataResponse.ok) throw new Error('Failed to save metadata');

        // Then save revision content
        let body = {};

        if (currentModalTab === 'prompt') {
            const template = document.getElementById('edit-prompt-template').value;
            if (!template.trim()) {
                alert('プロンプトテンプレートを入力してください / Please enter a prompt template');
                return;
            }
            body.prompt_template = template;
        } else {
            const parserType = document.getElementById('edit-parser-type').value;
            const parserConfigText = document.getElementById('edit-parser-config').value;

            try {
                const parsed = JSON.parse(parserConfigText);
                parsed.type = parserType;
                body.parser_config = JSON.stringify(parsed);
            } catch (e) {
                body.parser_config = JSON.stringify({type: parserType});
            }
        }

        const response = await fetch(`/api/prompts/${currentModalPromptId}/revisions/latest`, {
            method: 'PUT',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify(body)
        });

        if (!response.ok) throw new Error('Failed to save');

        const result = await response.json();

        if (result.is_new) {
            showStatus(`保存しました (Rev.${result.revision}) / Saved (Rev.${result.revision})`, 'success');
        } else {
            showStatus('保存しました / Saved', 'success');
        }

        closeModal();

        // Update main UI
        await loadExecutionTargets(currentProjectId);
    } catch (error) {
        alert(`エラー / Error: ${error.message}`);
    }
}

async function showAddPromptModalFromManagement() {
    // Show create prompt modal, then return to management modal
    const modalContent = `
        <div class="modal-header">
            新規プロンプト作成 / Create New Prompt
        </div>
        <div class="modal-body">
            <div class="form-group">
                <label>プロンプト名 / Prompt Name:</label>
                <input type="text" id="new-prompt-name" style="width: 100%; padding: 0.5rem; box-sizing: border-box;" placeholder="例: 要約プロンプト">
            </div>
            <div class="form-group">
                <label>説明 / Description:</label>
                <input type="text" id="new-prompt-description" style="width: 100%; padding: 0.5rem; box-sizing: border-box;" placeholder="例: テキストを要約するプロンプト">
            </div>
            <div class="form-group">
                <label>プロンプトテンプレート / Prompt Template:</label>
                <textarea id="new-prompt-template" rows="8" style="font-family: 'Courier New', monospace; width: 100%; box-sizing: border-box;">以下の指示に従って回答してください。

{{INPUT:TEXT10}}

回答:</textarea>
            </div>
        </div>
        <div class="modal-footer">
            <button class="btn btn-secondary" onclick="showPromptManagementModal('${currentModalTab}')">戻る / Back</button>
            <button class="btn btn-primary" onclick="createPromptAndReturn()">作成 / Create</button>
        </div>
    `;
    showModal(modalContent);
}

async function createPromptAndReturn() {
    const name = document.getElementById('new-prompt-name').value.trim();
    const description = document.getElementById('new-prompt-description').value.trim();
    const template = document.getElementById('new-prompt-template').value;

    if (!name) {
        alert('プロンプト名を入力してください / Please enter a prompt name');
        return;
    }

    try {
        const response = await fetch(`/api/projects/${currentProjectId}/prompts`, {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({
                name: name,
                description: description,
                prompt_template: template
            })
        });

        if (!response.ok) throw new Error('Failed to create prompt');

        const newPrompt = await response.json();
        showStatus(`プロンプト「${name}」を作成しました / Created prompt "${name}"`, 'success');

        // Select the new prompt and return to management modal
        currentModalPromptId = newPrompt.id;
        currentPromptId = newPrompt.id;
        await showPromptManagementModal(currentModalTab);

        // Also update main UI
        await loadExecutionTargets(currentProjectId);
    } catch (error) {
        alert(`エラー / Error: ${error.message}`);
    }
}

async function deletePromptFromModal() {
    const prompt = currentModalPromptData;
    if (!prompt) return;

    try {
        // Check if prompt is used in any workflows (for informational purposes)
        const usageResponse = await fetch(`/api/prompts/${currentModalPromptId}/usage`);
        let confirmMessage = `プロンプト「${prompt.name}」を削除しますか？\nDelete prompt "${prompt.name}"?`;

        if (usageResponse.ok) {
            const usage = await usageResponse.json();
            if (usage.is_used) {
                // Show usage info (soft delete won't break workflows)
                const workflowDetails = usage.workflows.map(wf => {
                    const steps = wf.step_names.join(', ');
                    return `  • ${wf.name} (ステップ: ${steps})`;
                }).join('\n');

                confirmMessage = `プロンプト「${prompt.name}」を削除しますか？\n\n` +
                    `📋 使用中のワークフロー (${usage.workflow_count}件):\n` +
                    `${workflowDetails}\n\n` +
                    `※ 削除後もワークフローは動作しますが、プロンプトは「（削除済み）」と表示されます。`;
            }
        }

        if (!confirm(confirmMessage)) {
            return;
        }

        const response = await fetch(`/api/prompts/${currentModalPromptId}`, {
            method: 'DELETE'
        });

        if (!response.ok) {
            const error = await response.json();
            if (error.detail && typeof error.detail === 'object') {
                throw new Error(error.detail.message || 'Failed to delete prompt');
            }
            throw new Error(error.detail || 'Failed to delete prompt');
        }

        showStatus(`プロンプトを削除しました / Prompt deleted`, 'success');

        // Reload management modal with first available prompt
        currentModalPromptId = null;
        currentPromptId = null;

        const targetsResponse = await fetch(`/api/projects/${currentProjectId}/execution-targets`);
        if (targetsResponse.ok) {
            const targets = await targetsResponse.json();
            if (targets.prompts && targets.prompts.length > 0) {
                currentModalPromptId = targets.prompts[0].id;
                await renderPromptManagementModal(targets.prompts);
            } else {
                closeModal();
            }
        }

        // Update main UI
        await loadExecutionTargets(currentProjectId);
    } catch (error) {
        alert(`エラー / Error: ${error.message}`);
    }
}

// Keep old function as alias for backward compatibility
async function showEditPromptModalNewArch() {
    await showPromptManagementModal('prompt');
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
 * NEW ARCHITECTURE: Save prompt revision using PromptRevision API
 */
async function savePromptRevisionNewArch() {
    const newTemplate = document.getElementById('edit-prompt-template').value;
    if (!newTemplate.trim()) {
        alert('プロンプトテンプレートを入力してください / Please enter a prompt template');
        return;
    }

    try {
        const response = await fetch(`/api/prompts/${currentPromptId}/revisions/latest`, {
            method: 'PUT',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({
                prompt_template: newTemplate
            })
        });

        if (!response.ok) throw new Error('Failed to save revision');

        const result = await response.json();
        closeModal();

        // Reload execution targets to refresh the prompt data
        await loadExecutionTargets(currentProjectId);

        // Re-select the current prompt
        const targetSelect = document.getElementById('single-target-select');
        if (targetSelect) {
            targetSelect.value = `prompt:${currentPromptId}`;
        }

        // Reload the prompt config
        const prompt = currentExecutionTargets?.prompts?.find(p => p.id === currentPromptId);
        if (prompt) {
            await loadPromptConfig(prompt);
        }

        if (result.is_new) {
            showStatus(`新しいリビジョン ${result.revision} を作成しました / New revision ${result.revision} created`, 'success');
        } else {
            showStatus('変更がありませんでした / No changes detected', 'info');
        }
    } catch (error) {
        alert(`エラー / Error: ${error.message}`);
    }
}

/**
 * NEW ARCHITECTURE: Load prompt revision content into the editor
 */
async function loadPromptRevisionContent(revisionNumber, type) {
    try {
        const response = await fetch(`/api/prompts/${currentPromptId}/revisions`);
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
 * NEW ARCHITECTURE: Restore a past prompt revision
 */
async function restorePromptRevision(type) {
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
        const response = await fetch(`/api/prompts/${currentPromptId}/revisions/${revisionNumber}/restore`, {
            method: 'POST'
        });

        if (!response.ok) throw new Error('Failed to restore revision');

        const result = await response.json();
        closeModal();

        // Reload execution targets
        await loadExecutionTargets(currentProjectId);

        // Re-select the current prompt
        const targetSelect = document.getElementById('single-target-select');
        if (targetSelect) {
            targetSelect.value = `prompt:${currentPromptId}`;
        }

        // Reload the prompt config
        const prompt = currentExecutionTargets?.prompts?.find(p => p.id === currentPromptId);
        if (prompt) {
            await loadPromptConfig(prompt);
        }

        showStatus(`リビジョン ${revisionNumber} を復元しました（新リビジョン: ${result.revision}）`, 'success');
    } catch (error) {
        alert(`エラー / Error: ${error.message}`);
    }
}

/**
 * Show edit parser modal
 * NEW ARCHITECTURE: Uses PromptRevision if currentPromptId is set
 * Specification: docs/req.txt section 6.2 (Response Parser)
 */
async function showEditParserModal() {
    // NEW ARCHITECTURE: Use currentPromptId if available
    if (currentSelectionType === 'prompt' && currentPromptId) {
        await showEditParserModalNewArch();
        return;
    }

    // Fallback to old behavior
    try {
        const [projectResponse, revisionsResponse] = await Promise.all([
            fetch(`/api/projects/${currentProjectId}`),
            fetch(`/api/projects/${currentProjectId}/revisions`)
        ]);

        if (!projectResponse.ok) throw new Error('Failed to load project');
        const project = await projectResponse.json();
        const revisions = revisionsResponse.ok ? await revisionsResponse.json() : [];

        const parserConfig = project.parser_config || {type: 'none'};
        const parserJson = JSON.stringify(parserConfig, null, 2);

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
                <!-- Inline JSON to CSV Converter -->
                <div id="json-csv-converter-section" style="margin-top: 10px; border: 1px solid #9b59b6; border-radius: 5px; display: none;">
                    <div style="background: #9b59b6; color: white; padding: 8px 12px; display: flex; justify-content: space-between; align-items: center;">
                        <span style="font-weight: bold;">📊 JSON → CSV 変換</span>
                        <button onclick="toggleJsonCsvConverter()" style="background: transparent; border: 1px solid white; color: white; padding: 2px 8px; border-radius: 3px; cursor: pointer; font-size: 0.8rem;">閉じる</button>
                    </div>
                    <div style="padding: 10px;">
                        <div style="display: flex; gap: 10px;">
                            <div style="flex: 1;">
                                <label style="font-size: 0.85rem; font-weight: bold; display: block; margin-bottom: 3px;">サンプルJSON入力:</label>
                                <textarea id="json-sample-input" rows="8" style="font-family: 'Courier New', monospace; width: 100%; font-size: 0.85rem;" placeholder='{"field1": "value", "field2": {"nested": "data"}}'></textarea>
                            </div>
                            <div style="display: flex; flex-direction: column; justify-content: center; gap: 5px;">
                                <button onclick="convertJsonToCsvTemplateInline()" style="background: #9b59b6; color: white; border: none; padding: 8px 12px; border-radius: 3px; cursor: pointer; font-size: 0.85rem;">🔄 変換</button>
                                <button onclick="applyGeneratedParserConfigInline()" style="background: #27ae60; color: white; border: none; padding: 8px 12px; border-radius: 3px; cursor: pointer; font-size: 0.85rem;">✅ 適用</button>
                            </div>
                            <div style="flex: 1;">
                                <label style="font-size: 0.85rem; font-weight: bold; display: block; margin-bottom: 3px;">生成された設定:</label>
                                <textarea id="generated-parser-config-inline" rows="8" style="font-family: 'Courier New', monospace; width: 100%; font-size: 0.85rem; background: #f8f9fa;" readonly placeholder="変換結果がここに表示されます"></textarea>
                            </div>
                        </div>
                        <div style="margin-top: 5px;">
                            <label style="font-size: 0.85rem; font-weight: bold;">CSVヘッダープレビュー:</label>
                            <input type="text" id="csv-header-preview-inline" readonly style="width: 100%; font-family: 'Courier New', monospace; font-size: 0.85rem; background: #f8f9fa; padding: 4px;" placeholder="ヘッダーがここに表示されます">
                        </div>
                    </div>
                </div>
            </div>
            <div class="modal-footer" style="display: flex; justify-content: space-between; flex-wrap: wrap; gap: 0.5rem;">
                <button id="json-csv-toggle-btn" class="btn" onclick="toggleJsonCsvConverter()" style="background-color: transparent; border: 1px solid #9b59b6; color: #9b59b6;">📊 JSON→CSV</button>
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
 * NEW ARCHITECTURE: Show edit parser modal using PromptRevision
 * Now redirects to unified prompt management modal with parser tab
 */
async function showEditParserModalNewArch() {
    await showPromptManagementModal('parser');
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

/**
 * NEW ARCHITECTURE: Save parser revision using PromptRevision API
 */
async function saveParserRevisionNewArch() {
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
        const response = await fetch(`/api/prompts/${currentPromptId}/revisions/latest`, {
            method: 'PUT',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({
                parser_config: JSON.stringify(parserConfig)
            })
        });

        if (!response.ok) throw new Error('Failed to save revision');

        const result = await response.json();
        closeModal();

        // Reload execution targets
        await loadExecutionTargets(currentProjectId);

        // Re-select the current prompt
        const targetSelect = document.getElementById('single-target-select');
        if (targetSelect) {
            targetSelect.value = `prompt:${currentPromptId}`;
        }

        // Reload the prompt config
        const prompt = currentExecutionTargets?.prompts?.find(p => p.id === currentPromptId);
        if (prompt) {
            await loadPromptConfig(prompt);
        }

        if (result.is_new) {
            showStatus(`新しいリビジョン ${result.revision} を作成しました / New revision ${result.revision} created`, 'success');
        } else {
            showStatus('変更がありませんでした / No changes detected', 'info');
        }
    } catch (error) {
        alert(`エラー / Error: ${error.message}`);
    }
}

// ========== BATCH EXECUTION EDIT MODALS ==========

/**
 * Show batch edit prompt modal
 * Now uses the unified prompt management modal
 */
async function showBatchEditPromptModal() {
    const selectValue = document.getElementById('batch-project-select').value;
    if (!selectValue) {
        alert('プロジェクトを選択してください / Please select a project');
        return;
    }

    const parsed = parseSelectValue(selectValue);
    if (!parsed || parsed.type !== 'project' || !parsed.id) {
        alert('プロジェクトを選択してください / Please select a project');
        return;
    }

    // Get selected prompt ID from batch prompt selector
    const batchPromptSelect = document.getElementById('batch-prompt-select');
    const promptId = batchPromptSelect && batchPromptSelect.value ? parseInt(batchPromptSelect.value) : null;

    // Open the unified prompt editor window
    await openPromptEditorWindow(parsed.id, promptId, null);
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
    const selectValue = document.getElementById('batch-project-select').value;
    if (!selectValue) {
        alert('プロジェクトを選択してください / Please select a project');
        return;
    }

    const parsed = parseSelectValue(selectValue);
    if (!parsed || parsed.type !== 'project' || !parsed.id) {
        alert('プロジェクトを選択してください / Please select a project');
        return;
    }
    const projectId = parsed.id;

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
                <!-- Inline JSON to CSV Converter -->
                <div id="json-csv-converter-section" style="margin-top: 10px; border: 1px solid #9b59b6; border-radius: 5px; display: none;">
                    <div style="background: #9b59b6; color: white; padding: 8px 12px; display: flex; justify-content: space-between; align-items: center;">
                        <span style="font-weight: bold;">📊 JSON → CSV 変換</span>
                        <button onclick="toggleJsonCsvConverter()" style="background: transparent; border: 1px solid white; color: white; padding: 2px 8px; border-radius: 3px; cursor: pointer; font-size: 0.8rem;">閉じる</button>
                    </div>
                    <div style="padding: 10px;">
                        <div style="display: flex; gap: 10px;">
                            <div style="flex: 1;">
                                <label style="font-size: 0.85rem; font-weight: bold; display: block; margin-bottom: 3px;">サンプルJSON入力:</label>
                                <textarea id="json-sample-input" rows="8" style="font-family: 'Courier New', monospace; width: 100%; font-size: 0.85rem;" placeholder='{"field1": "value", "field2": {"nested": "data"}}'></textarea>
                            </div>
                            <div style="display: flex; flex-direction: column; justify-content: center; gap: 5px;">
                                <button onclick="convertJsonToCsvTemplateInline()" style="background: #9b59b6; color: white; border: none; padding: 8px 12px; border-radius: 3px; cursor: pointer; font-size: 0.85rem;">🔄 変換</button>
                                <button onclick="applyGeneratedParserConfigInline()" style="background: #27ae60; color: white; border: none; padding: 8px 12px; border-radius: 3px; cursor: pointer; font-size: 0.85rem;">✅ 適用</button>
                            </div>
                            <div style="flex: 1;">
                                <label style="font-size: 0.85rem; font-weight: bold; display: block; margin-bottom: 3px;">生成された設定:</label>
                                <textarea id="generated-parser-config-inline" rows="8" style="font-family: 'Courier New', monospace; width: 100%; font-size: 0.85rem; background: #f8f9fa;" readonly placeholder="変換結果がここに表示されます"></textarea>
                            </div>
                        </div>
                        <div style="margin-top: 5px;">
                            <label style="font-size: 0.85rem; font-weight: bold;">CSVヘッダープレビュー:</label>
                            <input type="text" id="csv-header-preview-inline" readonly style="width: 100%; font-family: 'Courier New', monospace; font-size: 0.85rem; background: #f8f9fa; padding: 4px;" placeholder="ヘッダーがここに表示されます">
                        </div>
                    </div>
                </div>
            </div>
            <div class="modal-footer" style="display: flex; justify-content: space-between; flex-wrap: wrap; gap: 0.5rem;">
                <button id="json-csv-toggle-btn" class="btn" onclick="toggleJsonCsvConverter()" style="background-color: transparent; border: 1px solid #9b59b6; color: #9b59b6;">📊 JSON→CSV</button>
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
    // Load datasets and prompts for currently selected project (if any)
    const projectSelect = document.getElementById('batch-project-select');
    if (projectSelect && projectSelect.value) {
        const parsed = parseSelectValue(projectSelect.value);
        if (parsed && parsed.type === 'project' && parsed.id) {
            await loadDatasetsForProject(parsed.id);
            await loadBatchPromptsForProject(parsed.id);
            await loadBatchJobHistory(parsed.id);
        }
    }
}

async function loadBatchJobHistory(projectId) {
    try {
        // Reset pagination state for batch history
        batchHistoryOffset = 0;
        batchHistoryHasMore = true;

        // Get batch-type jobs for this project (first page only)
        const response = await fetch(`/api/projects/${projectId}/jobs?limit=${BATCH_HISTORY_PAGE_SIZE}&offset=0&job_type=batch`);
        const batchJobs = await response.json();

        // Update pagination state
        batchHistoryHasMore = batchJobs.length >= BATCH_HISTORY_PAGE_SIZE;
        batchHistoryOffset = batchJobs.length;

        renderBatchHistory(batchJobs);
    } catch (error) {
        const container = document.getElementById('batch-jobs-list');
        if (container) {
            container.innerHTML = '<p class="info">バッチジョブの履歴を読み込めませんでした / Failed to load batch job history</p>';
        }
    }
}

let currentBatchJobs = [];

function renderBatchHistory(jobs, append = false) {
    const container = document.getElementById('batch-jobs-list');
    if (!container) return;

    // Always remove existing "Load more" link first when appending
    if (append) {
        const existingLoadMore = container.querySelector('.load-more-link');
        if (existingLoadMore) {
            existingLoadMore.remove();
        }
    }

    // Store jobs for later use
    if (append) {
        currentBatchJobs = [...currentBatchJobs, ...(jobs || [])];
    } else {
        currentBatchJobs = jobs || [];
    }

    // Handle empty jobs
    if (!jobs || jobs.length === 0) {
        if (!append) {
            container.innerHTML = '<p class="info">バッチジョブの履歴はまだありません / No batch jobs yet</p>';
        }
        // When append mode with no new items, just update Load More button state
        if (append && batchHistoryHasMore) {
            container.insertAdjacentHTML('beforeend', `
                <div class="load-more-link" onclick="loadMoreBatchHistory()">
                    さらに表示 / Load more...
                </div>
            `);
        }
        return;
    }

    const jobsHtml = jobs.map(job => {
        const createdAt = formatJST(job.created_at);
        const finishedAt = formatJST(job.finished_at);
        const turnaround = job.turnaround_ms ? `${(job.turnaround_ms / 1000).toFixed(1)}s` : 'N/A';
        const itemCount = job.items ? job.items.length : 0;
        const modelName = job.model_name || '-';
        const promptName = job.prompt_name || '-';

        // Show delete button for pending/running jobs
        const canDelete = job.status === 'pending' || job.status === 'running';
        const deleteBtn = canDelete ?
            `<button class="delete-job-btn" onclick="event.stopPropagation(); deleteJob(${job.id}, 'batch')" title="ジョブを削除">🗑️</button>` : '';

        return `
            <div class="history-item" data-job-id="${job.id}">
                <div class="job-header">
                    <div class="job-id">Batch Job #${job.id} (${itemCount} items)</div>
                    ${deleteBtn}
                </div>
                <div class="prompt-info">🎯 ${promptName}</div>
                <div class="timestamp">実行: ${createdAt}</div>
                <div class="timestamp">完了: ${finishedAt}</div>
                <div class="turnaround">モデル: ${modelName} | 実行時間: ${turnaround}</div>
                <span class="status ${job.status}">${job.status}</span>
            </div>
        `;
    }).join('');

    // Add "Load more" link if there are more jobs
    const loadMoreHtml = batchHistoryHasMore ? `
        <div class="load-more-link" onclick="loadMoreBatchHistory()">
            さらに表示 / Load more...
        </div>
    ` : '';

    if (append) {
        container.insertAdjacentHTML('beforeend', jobsHtml + loadMoreHtml);
    } else {
        container.innerHTML = jobsHtml + loadMoreHtml;
    }

    // Add click event listeners after rendering
    document.querySelectorAll('#batch-jobs-list .history-item').forEach(item => {
        item.addEventListener('click', () => {
            const jobId = parseInt(item.dataset.jobId);
            selectBatchJob(jobId);
        });
    });
}

let batchHistoryLoading = false;

async function loadMoreBatchHistory() {
    // Prevent duplicate clicks while loading
    if (batchHistoryLoading) return;
    batchHistoryLoading = true;

    // Update button to show loading state
    const loadMoreBtn = document.querySelector('#batch-jobs-list .load-more-link');
    if (loadMoreBtn) {
        loadMoreBtn.textContent = '読み込み中... / Loading...';
        loadMoreBtn.style.pointerEvents = 'none';
    }

    try {
        const projectSelect = document.getElementById('batch-project-select');
        if (!projectSelect || !projectSelect.value) return;

        const parsed = parseSelectValue(projectSelect.value);
        if (!parsed || parsed.type !== 'project' || !parsed.id) return;

        // Fetch next page of batch-type jobs
        const response = await fetch(`/api/projects/${parsed.id}/jobs?limit=${BATCH_HISTORY_PAGE_SIZE}&offset=${batchHistoryOffset}&job_type=batch`);
        if (!response.ok) throw new Error('Failed to load more jobs');
        const batchJobs = await response.json();

        // Update pagination state BEFORE rendering
        batchHistoryHasMore = batchJobs.length >= BATCH_HISTORY_PAGE_SIZE;
        batchHistoryOffset += batchJobs.length;

        // Append to existing history (or update Load More button state)
        renderBatchHistory(batchJobs, true);
    } catch (error) {
        showStatus('履歴の読み込みに失敗しました / Failed to load more history', 'error');
    } finally {
        batchHistoryLoading = false;
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
    const selectValue = document.getElementById('batch-project-select').value;
    const promptSelectValue = document.getElementById('batch-prompt-select').value;
    const datasetId = document.getElementById('batch-dataset-select').value;
    const includeCsvHeader = document.getElementById('batch-include-csv-header')?.checked ?? true;
    const modelName = document.getElementById('batch-model-select').value;

    // Parse selection value
    const { type, id } = parseSelectValue(selectValue);

    if (!selectValue || !datasetId) {
        alert('プロジェクト/ワークフローとデータセットを選択してください / Please select project/workflow and dataset');
        return;
    }

    // For project execution, prompt must be selected
    if (type !== 'workflow' && !promptSelectValue) {
        alert('プロンプトを選択してください / Please select a prompt');
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

        if (type === 'workflow') {
            // Workflow batch execution - execute workflow for each dataset row
            await executeBatchWorkflow(id, parseInt(datasetId), modelName, modelParams.temperature || 0.7);
        } else if (promptSelectValue === 'all') {
            // All prompts execution - run all prompts against the dataset sequentially
            await executeBatchAllPrompts(id, parseInt(datasetId), includeCsvHeader, modelName, modelParams);
        } else {
            // Single prompt batch execution
            const response = await fetch('/api/run/batch', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({
                    project_id: id,
                    prompt_id: parseInt(promptSelectValue),
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
            pollBatchJobProgress(result.job_id, id);
        }

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

/**
 * Execute batch for all prompts in a project
 * Uses server-side API that creates ALL jobs upfront, ensuring execution
 * continues even if browser is closed.
 */
async function executeBatchAllPrompts(projectId, datasetId, includeCsvHeader, modelName, modelParams, force = false) {
    const executeBtn = document.getElementById('btn-batch-execute');
    const originalText = executeBtn.textContent;

    try {
        executeBtn.textContent = '全プロンプト実行開始中... / Starting all prompts...';

        // Call server-side API that creates ALL jobs upfront
        const response = await fetch('/api/run/batch-all', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({
                project_id: projectId,
                dataset_id: datasetId,
                include_csv_header: includeCsvHeader,
                model_name: modelName,
                temperature: modelParams.temperature || 0.7,
                force: force
            })
        });

        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.detail || 'Failed to start batch-all execution');
        }

        const result = await response.json();

        // Check if there are running jobs and force=false
        if (result.has_running_jobs && !force) {
            // Restore button immediately
            executeBtn.textContent = originalText;
            executeBtn.disabled = false;

            // Show confirmation dialog
            const runningCount = result.running_jobs_count;
            const confirmed = confirm(
                `既に ${runningCount} 件の実行中/待機中ジョブがあります。\n` +
                `追加で新しいジョブを作成しますか？\n\n` +
                `There are already ${runningCount} running/pending jobs.\n` +
                `Do you want to add new jobs?`
            );

            if (confirmed) {
                // Re-call with force=true
                return await executeBatchAllPrompts(projectId, datasetId, includeCsvHeader, modelName, modelParams, true);
            } else {
                showStatus('実行をキャンセルしました / Execution cancelled', 'info');
                return;
            }
        }

        // Check if there are recently created jobs (within 5 minutes) and force=false
        if (result.has_recent_jobs && !force) {
            // Restore button immediately
            executeBtn.textContent = originalText;
            executeBtn.disabled = false;

            // Show confirmation dialog
            const recentCount = result.recent_jobs_count;
            const confirmed = confirm(
                `過去5分以内に ${recentCount} 件のジョブが作成されています。\n` +
                `追加で新しいジョブを作成しますか？\n\n` +
                `${recentCount} jobs were created in the last 5 minutes.\n` +
                `Do you want to add new jobs?`
            );

            if (confirmed) {
                // Re-call with force=true
                return await executeBatchAllPrompts(projectId, datasetId, includeCsvHeader, modelName, modelParams, true);
            } else {
                showStatus('実行をキャンセルしました / Execution cancelled', 'info');
                return;
            }
        }

        const jobIds = result.job_ids;
        const jobs = result.jobs;

        // Store first job ID for potential cancellation
        if (jobIds.length > 0) {
            currentBatchJobId = jobIds[0];
        }

        // Show confirmation that all jobs are created
        executeBtn.textContent = `${jobIds.length} ジョブ作成完了 / ${jobIds.length} jobs created`;

        // Reload batch history immediately to show all created jobs
        await loadBatchJobHistory(projectId);

        // Poll for first job's progress (optional - just for UI feedback)
        // All jobs will execute on server even if browser is closed
        if (jobIds.length > 0) {
            pollBatchAllProgress(jobIds, projectId);
        }

        // Restore button after a short delay
        setTimeout(() => {
            executeBtn.textContent = originalText;
            executeBtn.disabled = false;
            executeBtn.style.background = '';
        }, 2000);

        // Show message about browser-independent execution
        showStatus(
            `${jobIds.length} 件のバッチジョブを作成しました。サーバー上で順次実行されます（ブラウザを閉じても実行継続） / ` +
            `${jobIds.length} batch jobs created. They will execute on server (continues even if browser is closed)`,
            'success'
        );

    } catch (error) {
        throw error;
    }
}

/**
 * Poll progress for batch-all execution (optional UI feedback)
 * Jobs will complete on server regardless of this polling
 */
async function pollBatchAllProgress(jobIds, projectId) {
    const executeBtn = document.getElementById('btn-batch-execute');
    let completedCount = 0;

    const checkInterval = setInterval(async () => {
        try {
            const response = await fetch(`/api/projects/${projectId}/jobs?job_type=batch&limit=${jobIds.length * 2}`);
            if (!response.ok) return;

            const jobs = await response.json();

            // Count completed jobs from our batch (including cancelled)
            completedCount = 0;
            for (const jobId of jobIds) {
                const job = jobs.find(j => j.id === jobId);
                if (job && (job.status === 'done' || job.status === 'error' || job.status === 'cancelled')) {
                    completedCount++;
                }
            }

            // Update UI
            if (completedCount < jobIds.length) {
                executeBtn.textContent = `実行中 ${completedCount}/${jobIds.length}... / Running ${completedCount}/${jobIds.length}...`;
            }

            // All done - reload history and stop polling
            if (completedCount >= jobIds.length) {
                clearInterval(checkInterval);
                await loadBatchJobHistory(projectId);
                executeBtn.textContent = '▶ バッチ実行開始 / Start Batch';
                executeBtn.disabled = false;
                executeBtn.style.background = '';
                document.getElementById('btn-stop-batch').style.display = 'none';
                currentBatchJobId = null;

                showStatus(
                    `全プロンプト実行完了！ ${jobIds.length} ジョブ完了 / All prompts executed! ${jobIds.length} jobs completed`,
                    'success'
                );
            }
        } catch (error) {
            console.error('Error polling batch-all progress:', error);
        }
    }, 3000); // Check every 3 seconds

    // Stop polling after 30 minutes max (jobs continue on server)
    setTimeout(() => {
        clearInterval(checkInterval);
    }, 30 * 60 * 1000);
}

/**
 * Wait for a batch job to complete (polling)
 */
async function waitForBatchJobCompletion(jobId, projectId) {
    return new Promise((resolve) => {
        const checkInterval = setInterval(async () => {
            try {
                const response = await fetch(`/api/projects/${projectId}/jobs`);
                const jobs = await response.json();
                const job = jobs.find(j => j.id === jobId);

                if (!job || job.status === 'done' || job.status === 'error' || job.status === 'cancelled') {
                    clearInterval(checkInterval);
                    resolve();
                }
            } catch (error) {
                console.error('Error checking job status:', error);
                clearInterval(checkInterval);
                resolve();
            }
        }, 2000); // Check every 2 seconds
    });
}

/**
 * Execute workflow in batch mode using dataset rows as input parameters
 * @param {number} workflowId - Workflow ID
 * @param {number} datasetId - Dataset ID
 * @param {string} modelName - Model name
 * @param {number} temperature - Temperature setting
 */
async function executeBatchWorkflow(workflowId, datasetId, modelName, temperature) {
    console.log(`🔄 Executing workflow ${workflowId} in batch mode with dataset ${datasetId}`);

    const executeBtn = document.getElementById('btn-batch-execute');
    const originalText = executeBtn.textContent;

    try {
        // Fetch dataset data
        const datasetResponse = await fetch(`/api/datasets/${datasetId}`);
        if (!datasetResponse.ok) throw new Error('Failed to load dataset');
        const dataset = await datasetResponse.json();

        if (!dataset.data || dataset.data.length === 0) {
            throw new Error('データセットが空です / Dataset is empty');
        }

        const totalRows = dataset.data.length;
        const workflowJobIds = [];

        // Create a results container
        const container = document.getElementById('batch-result');
        if (container) {
            container.innerHTML = `
                <div class="batch-progress">
                    <h4>ワークフローバッチ実行中... / Workflow Batch Execution...</h4>
                    <div id="workflow-batch-progress">0 / ${totalRows} 完了</div>
                    <div id="workflow-batch-jobs"></div>
                </div>
            `;
        }

        // Execute workflow for each row in the dataset
        for (let i = 0; i < totalRows; i++) {
            const row = dataset.data[i];

            // Update progress
            const progressEl = document.getElementById('workflow-batch-progress');
            if (progressEl) {
                progressEl.textContent = `${i + 1} / ${totalRows} 実行中...`;
            }

            executeBtn.textContent = `実行中... (${i + 1}/${totalRows})`;

            // Execute workflow with row data as input params
            const requestBody = {
                input_params: row,
                model_name: modelName,
                temperature: temperature
            };

            const response = await fetch(`/api/workflows/${workflowId}/run`, {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify(requestBody)
            });

            if (!response.ok) {
                console.error(`Failed to execute workflow for row ${i + 1}`);
                continue;
            }

            const result = await response.json();
            workflowJobIds.push(result.id);

            // Add to jobs list
            const jobsEl = document.getElementById('workflow-batch-jobs');
            if (jobsEl) {
                jobsEl.innerHTML += `
                    <div class="workflow-batch-job" onclick="selectWorkflowJob(${result.id})">
                        <span>Row ${i + 1}: WF-Job #${result.id}</span>
                        <span class="status-pending">pending</span>
                    </div>
                `;
            }

            // Small delay between executions to avoid overwhelming the API
            await new Promise(resolve => setTimeout(resolve, 200));
        }

        // Update final progress
        const progressEl = document.getElementById('workflow-batch-progress');
        if (progressEl) {
            progressEl.textContent = `${totalRows} / ${totalRows} 完了！ジョブをポーリング中...`;
        }

        // Start polling for all workflow jobs
        pollWorkflowBatchJobs(workflowJobIds);

        showStatus(`ワークフローバッチ実行開始！ ${totalRows} 件のジョブを作成しました`, 'success');

    } finally {
        // Restore button
        executeBtn.disabled = false;
        executeBtn.textContent = originalText;
        executeBtn.style.background = '';
    }
}

/**
 * Poll multiple workflow batch jobs for completion
 * @param {Array<number>} jobIds - Array of workflow job IDs
 */
async function pollWorkflowBatchJobs(jobIds) {
    const pollInterval = setInterval(async () => {
        let allComplete = true;
        let completedCount = 0;

        for (const jobId of jobIds) {
            try {
                const response = await fetch(`/api/workflow-jobs/${jobId}`);
                if (!response.ok) continue;

                const job = await response.json();

                // Update status in UI
                const jobElements = document.querySelectorAll(`.workflow-batch-job`);
                jobElements.forEach(el => {
                    if (el.textContent.includes(`WF-Job #${jobId}`)) {
                        const statusEl = el.querySelector('span:last-child');
                        if (statusEl) {
                            statusEl.className = `status-${job.status}`;
                            statusEl.textContent = job.status;
                        }
                    }
                });

                if (job.status === 'completed' || job.status === 'error') {
                    completedCount++;
                } else {
                    allComplete = false;
                }
            } catch (error) {
                console.error(`Failed to poll job ${jobId}:`, error);
            }
        }

        // Update progress
        const progressEl = document.getElementById('workflow-batch-progress');
        if (progressEl) {
            progressEl.textContent = `${completedCount} / ${jobIds.length} 完了`;
        }

        if (allComplete) {
            clearInterval(pollInterval);
            document.getElementById('btn-stop-batch').style.display = 'none';
            showStatus('ワークフローバッチ実行完了！', 'success');
        }
    }, 3000);
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

            // Check if job is complete (including cancelled)
            const isComplete = job.status === 'done' || job.status === 'error' || job.status === 'cancelled';
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
    const selectValue = e.target.value;
    const { type, id } = parseSelectValue(selectValue);

    if (type === 'workflow') {
        // For workflows, load datasets from the first step's project
        await loadDatasetsForWorkflow(id);
        // Clear prompt selector for workflows (not applicable)
        const promptSelect = document.getElementById('batch-prompt-select');
        if (promptSelect) {
            promptSelect.innerHTML = '<option value="">ワークフローでは不要 / Not needed for workflow</option>';
            promptSelect.disabled = true;
        }
        // Clear batch job history for workflows (TODO: implement workflow job history)
        const historyContainer = document.getElementById('batch-jobs-list');
        if (historyContainer) {
            historyContainer.innerHTML = '<p class="info">ワークフロージョブ履歴は準備中 / Workflow job history coming soon</p>';
        }
    } else {
        // Load datasets, prompts, and job history in parallel
        await Promise.all([
            loadDatasetsForProject(id),
            loadBatchPromptsForProject(id),
            loadBatchJobHistory(id)
        ]);
        const promptSelect = document.getElementById('batch-prompt-select');
        if (promptSelect) promptSelect.disabled = false;
    }
}

/**
 * Load prompts for batch execution project selector
 * Includes "All Prompts" option for running all prompts against dataset
 */
async function loadBatchPromptsForProject(projectId) {
    const select = document.getElementById('batch-prompt-select');
    if (!select) return;

    try {
        const response = await fetch(`/api/projects/${projectId}/prompts`);
        if (!response.ok) throw new Error('Failed to load prompts');
        const prompts = await response.json();

        let options = '<option value="">プロンプトを選択 / Select Prompt</option>';

        if (prompts.length > 1) {
            // Add "All Prompts" option only if there are multiple prompts
            options += `<option value="all">🔄 全プロンプト実行 / Run All Prompts (${prompts.length})</option>`;
        }

        prompts.forEach(prompt => {
            options += `<option value="${prompt.id}">${prompt.name}</option>`;
        });

        select.innerHTML = options;

        // Auto-select first prompt if only one
        if (prompts.length === 1) {
            select.value = prompts[0].id;
        }
    } catch (error) {
        console.error('Failed to load prompts for batch:', error);
        select.innerHTML = '<option value="">エラー / Error</option>';
    }
}

/**
 * Load datasets for workflow's first step project
 * @param {number} workflowId - Workflow ID
 */
async function loadDatasetsForWorkflow(workflowId) {
    try {
        // Get workflow details
        const workflowResponse = await fetch(`/api/workflows/${workflowId}`);
        if (!workflowResponse.ok) throw new Error('Failed to load workflow');
        const workflow = await workflowResponse.json();

        // Get first step's project ID
        if (workflow.steps && workflow.steps.length > 0) {
            const firstStepProjectId = workflow.steps[0].project_id;
            // Load datasets for the first step's project
            await loadDatasetsForProject(firstStepProjectId);
        } else {
            // No steps, show empty dataset list
            const select = document.getElementById('batch-dataset-select');
            if (select) {
                select.innerHTML = '<option value="">ステップがありません / No steps</option>';
            }
        }
    } catch (error) {
        console.error('Failed to load datasets for workflow:', error);
        const select = document.getElementById('batch-dataset-select');
        if (select) {
            select.innerHTML = '<option value="">エラー / Error</option>';
        }
    }
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
        // Load both projects and workflows in parallel
        const [projectsResponse, workflowsResponse] = await Promise.all([
            fetch('/api/projects'),
            fetch('/api/workflows')
        ]);

        allProjects = await projectsResponse.json();

        // Load workflows (may not exist yet, handle gracefully)
        if (workflowsResponse.ok) {
            allWorkflows = await workflowsResponse.json();
        } else {
            allWorkflows = [];
        }

        renderProjects();
        await updateProjectSelects();
    } catch (error) {
        // Failed to load projects - silently continue
        console.error('Failed to load projects/workflows:', error);
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

    // Build project options (no workflows - workflows are now selected in prompt/target selector)
    const projectOptions = allProjects.map(p => `<option value="project-${p.id}">${p.name}</option>`).join('');

    // Plain project options for settings (no workflows)
    const plainProjectOptions = allProjects.map(p => `<option value="${p.id}">${p.name}</option>`).join('');

    if (singleSelect) {
        singleSelect.innerHTML = projectOptions;
        // Set default project if configured
        let defaultLoaded = false;
        try {
            const response = await fetch('/api/settings/default-project');
            const data = await response.json();
            if (data.project_id) {
                singleSelect.value = `project-${data.project_id}`;
                currentProjectId = data.project_id;
                currentSelectionType = 'project';
                currentWorkflowId = null;
                // Trigger project change to load prompts
                await onProjectChange();
                defaultLoaded = true;
            }
        } catch (error) {
            console.error('Failed to load default project:', error);
        }

        // Fallback: if no default project, load execution targets for first project in list
        if (!defaultLoaded && singleSelect.value) {
            const { type, id } = parseSelectValue(singleSelect.value);
            if (type === 'project') {
                currentProjectId = id;
                currentSelectionType = 'project';
                currentWorkflowId = null;
                currentPromptId = null;
                // NEW ARCHITECTURE: Load execution targets instead of loadConfig
                await loadExecutionTargets(id);
            }
        }
    }

    if (batchSelect) {
        batchSelect.innerHTML = projectOptions;
        // Set default project if configured
        try {
            const response = await fetch('/api/settings/default-project');
            const data = await response.json();
            if (data.project_id) {
                batchSelect.value = `project-${data.project_id}`;
                // Load datasets for default project
                await loadDatasetsForProject(data.project_id);
            } else if (batchSelect.value) {
                // Auto-load datasets for first selection on batch tab if no default
                const { type, id } = parseSelectValue(batchSelect.value);
                if (type === 'project') {
                    await loadDatasetsForProject(id);
                }
            }
        } catch (error) {
            console.error('Failed to load default project for batch:', error);
            // Fallback to first selection
            if (batchSelect.value) {
                const { type, id } = parseSelectValue(batchSelect.value);
                if (type === 'project') {
                    await loadDatasetsForProject(id);
                }
            }
        }
    }

    if (defaultProjectSelect) {
        // Settings dropdown only shows projects, not workflows
        defaultProjectSelect.innerHTML = plainProjectOptions;
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

/**
 * Parse select value to extract type and ID
 * @param {string} value - Value in format "project-{id}" or "workflow-{id}"
 * @returns {{type: string, id: number}}
 */
function parseSelectValue(value) {
    if (!value) return { type: null, id: null };

    if (value.startsWith('workflow-')) {
        return { type: 'workflow', id: parseInt(value.replace('workflow-', '')) };
    } else if (value.startsWith('project-')) {
        return { type: 'project', id: parseInt(value.replace('project-', '')) };
    } else {
        // Legacy format - assume project ID
        return { type: 'project', id: parseInt(value) };
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

        container.innerHTML = models.map(model => {
            const privateIcon = model.is_private ? '&#128274; ' : '';
            return `<div class="badge badge-info">${privateIcon}${model.display_name || model.name || model}</div>`;
        }).join(' ');

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

            const privateIcon = model.is_private ? '<span title="Private Model" style="margin-right: 0.3rem; color: #e67e22;">&#128274;</span>' : '';

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
                            ${privateIcon}<strong>${model.display_name}</strong>
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

// Dataset import state
let importSelectedJobId = null;
let importIsWorkflowJob = false;  // Track if selected job is a workflow job
let importHasCsvData = false;  // Track if selected job has CSV data
let importJobsCache = [];
let importPromptsCache = [];  // Cache prompts/workflows with their types

function showImportDatasetModal() {
    const datasetsOptions = allDatasets.map(d =>
        `<option value="${d.id}">${escapeHtmlGlobal(d.name)} (${d.row_count}行)</option>`
    ).join('');

    showModal(`
        <div class="modal-header">データセットインポート / Import Dataset</div>
        <div class="modal-body">
            <!-- Tabs -->
            <div class="import-tabs">
                <button type="button" class="import-tab active" onclick="switchImportTab('excel')">Excel</button>
                <button type="button" class="import-tab" onclick="switchImportTab('csv')">CSV</button>
                <button type="button" class="import-tab" onclick="switchImportTab('results')">実行結果 / Results</button>
            </div>

            <!-- Excel Tab -->
            <div id="import-tab-excel" class="import-tab-content active">
                <div class="form-group">
                    <label>プロジェクト / Project:</label>
                    <select id="import-excel-project-id" onchange="updateExcelDatasetOptions()">
                        ${allProjects.map(p => `<option value="${p.id}">${escapeHtmlGlobal(p.name)}</option>`).join('')}
                    </select>
                </div>
                <div class="import-option-group">
                    <label>
                        <input type="radio" name="excel-mode" value="new" checked onchange="toggleExcelMode()">
                        新規データセット作成 / Create new dataset
                    </label>
                    <div id="excel-new-options" style="margin-top: 0.5rem; margin-left: 1.5rem;">
                        <input type="text" id="import-excel-dataset-name" placeholder="データセット名 / Dataset name">
                    </div>
                </div>
                <div class="import-option-group">
                    <label>
                        <input type="radio" name="excel-mode" value="append" onchange="toggleExcelMode()">
                        既存データセットに追加 / Append to existing
                    </label>
                    <div id="excel-append-options" class="import-option-select" style="display: none;">
                        <select id="import-excel-target-dataset">
                            <option value="">-- 選択 / Select --</option>
                            ${datasetsOptions}
                        </select>
                    </div>
                </div>
                <div class="form-group">
                    <label>範囲名 / Range Name:</label>
                    <input type="text" id="import-excel-range-name" value="DSRange">
                </div>
                <div class="form-group">
                    <label>Excelファイル / Excel File:</label>
                    <input type="file" id="import-excel-file" accept=".xlsx,.xls">
                </div>
            </div>

            <!-- CSV Tab -->
            <div id="import-tab-csv" class="import-tab-content">
                <div class="form-group">
                    <label>プロジェクト / Project:</label>
                    <select id="import-csv-project-id" onchange="updateCsvDatasetOptions()">
                        ${allProjects.map(p => `<option value="${p.id}">${escapeHtmlGlobal(p.name)}</option>`).join('')}
                    </select>
                </div>
                <div class="import-option-group">
                    <label>
                        <input type="radio" name="csv-mode" value="new" checked onchange="toggleCsvMode()">
                        新規データセット作成 / Create new dataset
                    </label>
                    <div id="csv-new-options" style="margin-top: 0.5rem; margin-left: 1.5rem;">
                        <input type="text" id="import-csv-dataset-name" placeholder="データセット名 / Dataset name">
                    </div>
                </div>
                <div class="import-option-group">
                    <label>
                        <input type="radio" name="csv-mode" value="append" onchange="toggleCsvMode()">
                        既存データセットに追加 / Append to existing
                    </label>
                    <div id="csv-append-options" class="import-option-select" style="display: none;">
                        <select id="import-csv-target-dataset">
                            <option value="">-- 選択 / Select --</option>
                            ${datasetsOptions}
                        </select>
                    </div>
                </div>
                <div class="csv-settings-grid">
                    <div class="form-group">
                        <label>文字コード / Encoding:</label>
                        <select id="import-csv-encoding">
                            <option value="utf-8">UTF-8</option>
                            <option value="utf-8-sig">UTF-8 (BOM)</option>
                            <option value="shift_jis">Shift_JIS</option>
                            <option value="cp932">CP932 (Windows日本語)</option>
                            <option value="euc-jp">EUC-JP</option>
                        </select>
                    </div>
                    <div class="form-group">
                        <label>デリミタ / Delimiter:</label>
                        <select id="import-csv-delimiter">
                            <option value=",">カンマ (,)</option>
                            <option value="&#9;">タブ (TAB)</option>
                            <option value=";">セミコロン (;)</option>
                            <option value="|">パイプ (|)</option>
                        </select>
                    </div>
                    <div class="form-group">
                        <label>クォート / Quote:</label>
                        <select id="import-csv-quotechar">
                            <option value="&quot;">ダブルクォート (")</option>
                            <option value="'">シングルクォート (')</option>
                            <option value="">なし / None</option>
                        </select>
                    </div>
                    <div class="form-group">
                        <label>ヘッダー / Header:</label>
                        <select id="import-csv-header">
                            <option value="1">1行目をヘッダーとして使用</option>
                            <option value="0">ヘッダーなし（自動生成）</option>
                        </select>
                    </div>
                </div>
                <div class="form-group">
                    <label>CSVファイル / CSV File:</label>
                    <input type="file" id="import-csv-file" accept=".csv,.txt,.tsv">
                </div>
            </div>

            <!-- Results Tab -->
            <div id="import-tab-results" class="import-tab-content">
                <div class="job-history-filters">
                    <select id="import-results-project" onchange="loadJobHistory()">
                        <option value="">プロジェクト / Project</option>
                        ${allProjects.map(p => `<option value="${p.id}">${escapeHtmlGlobal(p.name)}</option>`).join('')}
                    </select>
                    <select id="import-results-prompt" onchange="loadJobHistory()">
                        <option value="">プロンプト / Prompt</option>
                    </select>
                    <select id="import-results-type" onchange="loadJobHistory()">
                        <option value="">種別 / Type</option>
                        <option value="single">単発 / Single</option>
                        <option value="batch">バッチ / Batch</option>
                    </select>
                </div>
                <div class="job-history-list" id="import-job-history-list">
                    <div style="padding: 1rem; text-align: center; color: #64748b;">
                        プロジェクトを選択してください / Select a project
                    </div>
                </div>
                <div id="import-job-preview" class="job-preview-panel" style="display: none;">
                    <div class="job-preview-header">プレビュー / Preview</div>
                    <div id="import-job-preview-content" class="job-preview-csv"></div>
                </div>
                <div class="import-option-group">
                    <label>
                        <input type="radio" name="results-mode" value="new" checked onchange="toggleResultsMode()">
                        新規データセット作成 / Create new dataset
                    </label>
                    <div id="results-new-options" style="margin-top: 0.5rem; margin-left: 1.5rem;">
                        <input type="text" id="import-results-dataset-name" placeholder="データセット名 / Dataset name">
                    </div>
                </div>
                <div class="import-option-group">
                    <label>
                        <input type="radio" name="results-mode" value="append" onchange="toggleResultsMode()">
                        既存データセットに追加 / Append to existing
                    </label>
                    <div id="results-append-options" class="import-option-select" style="display: none;">
                        <select id="import-results-target-dataset">
                            <option value="">-- 選択 / Select --</option>
                            ${datasetsOptions}
                        </select>
                    </div>
                </div>
            </div>
        </div>
        <div class="modal-footer">
            <button class="btn btn-secondary" onclick="closeModal()">キャンセル / Cancel</button>
            <button id="import-submit-btn" class="btn btn-primary" onclick="executeDatasetImport()">インポート / Import</button>
        </div>
    `, 'import-modal-wide');

    // Reset state
    importSelectedJobId = null;
    importIsWorkflowJob = false;
    importHasCsvData = false;
    importJobsCache = [];

    // Update import button state based on initial tab
    updateImportButtonState();
}

function switchImportTab(tabName) {
    // Update tab buttons
    document.querySelectorAll('.import-tab').forEach(tab => tab.classList.remove('active'));
    event.target.classList.add('active');

    // Update tab content
    document.querySelectorAll('.import-tab-content').forEach(content => content.classList.remove('active'));
    document.getElementById(`import-tab-${tabName}`).classList.add('active');

    // Update import button state based on selected tab
    updateImportButtonState();
}

function updateImportButtonState() {
    const btn = document.getElementById('import-submit-btn');
    if (!btn) return;

    // Determine active tab
    const activeTab = document.querySelector('.import-tab-content.active');
    if (!activeTab) return;

    const tabId = activeTab.id;

    if (tabId === 'import-tab-results') {
        // Results tab: require job selection AND CSV data
        if (!importSelectedJobId || !importHasCsvData) {
            btn.disabled = true;
            if (!importSelectedJobId) {
                btn.title = 'ジョブを選択してください / Please select a job';
            } else if (!importHasCsvData) {
                btn.title = 'CSVデータがありません / No CSV data available';
            }
        } else {
            btn.disabled = false;
            btn.title = '';
        }
    } else {
        // Excel/CSV tabs: always enabled (file validation happens on import)
        btn.disabled = false;
        btn.title = '';
    }
}

function toggleExcelMode() {
    const mode = document.querySelector('input[name="excel-mode"]:checked').value;
    document.getElementById('excel-new-options').style.display = mode === 'new' ? 'block' : 'none';
    document.getElementById('excel-append-options').style.display = mode === 'append' ? 'block' : 'none';
}

function toggleCsvMode() {
    const mode = document.querySelector('input[name="csv-mode"]:checked').value;
    document.getElementById('csv-new-options').style.display = mode === 'new' ? 'block' : 'none';
    document.getElementById('csv-append-options').style.display = mode === 'append' ? 'block' : 'none';
}

function toggleResultsMode() {
    const mode = document.querySelector('input[name="results-mode"]:checked').value;
    document.getElementById('results-new-options').style.display = mode === 'new' ? 'block' : 'none';
    document.getElementById('results-append-options').style.display = mode === 'append' ? 'block' : 'none';
}

function updateExcelDatasetOptions() {
    const projectId = document.getElementById('import-excel-project-id').value;
    const select = document.getElementById('import-excel-target-dataset');
    select.innerHTML = '<option value="">-- 選択 / Select --</option>' +
        allDatasets.filter(d => d.project_id == projectId)
            .map(d => `<option value="${d.id}">${escapeHtmlGlobal(d.name)} (${d.row_count}行)</option>`)
            .join('');
}

function updateCsvDatasetOptions() {
    const projectId = document.getElementById('import-csv-project-id').value;
    const select = document.getElementById('import-csv-target-dataset');
    select.innerHTML = '<option value="">-- 選択 / Select --</option>' +
        allDatasets.filter(d => d.project_id == projectId)
            .map(d => `<option value="${d.id}">${escapeHtmlGlobal(d.name)} (${d.row_count}行)</option>`)
            .join('');
}

async function loadJobHistory() {
    const projectId = document.getElementById('import-results-project').value;
    const selectedValue = document.getElementById('import-results-prompt').value;
    const jobType = document.getElementById('import-results-type').value;

    // Update prompts dropdown when project changes
    if (projectId) {
        try {
            // Use execution-targets endpoint to get combined prompts and workflows
            const targetsResponse = await fetch(`/api/projects/${projectId}/execution-targets`);
            if (targetsResponse.ok) {
                const targets = await targetsResponse.json();
                // Combine prompts and workflows with type prefix
                const combined = [
                    ...(targets.prompts || []).map(p => ({ type: 'prompt', id: p.id, name: p.name })),
                    ...(targets.workflows || []).map(w => ({ type: 'workflow', id: w.id, name: w.name }))
                ];
                importPromptsCache = combined;  // Cache for type lookup
                const promptSelect = document.getElementById('import-results-prompt');
                const currentPromptValue = promptSelect.value;
                // Include type in option value: "prompt:123" or "workflow:456"
                promptSelect.innerHTML = '<option value="">プロンプト / Prompt</option>' +
                    combined.map(p => `<option value="${p.type}:${p.id}">${escapeHtmlGlobal(p.name)}</option>`).join('');
                // Restore selection if still valid
                if (combined.some(p => `${p.type}:${p.id}` === currentPromptValue)) {
                    promptSelect.value = currentPromptValue;
                }
            }
        } catch (e) {
            console.error('Failed to load prompts:', e);
        }
    }

    if (!projectId) {
        document.getElementById('import-job-history-list').innerHTML =
            '<div style="padding: 1rem; text-align: center; color: #64748b;">プロジェクトを選択してください / Select a project</div>';
        return;
    }

    try {
        let url = `/api/jobs?project_id=${projectId}&limit=50`;

        // Parse the selected value to get type and id
        if (selectedValue) {
            const [itemType, itemId] = selectedValue.split(':');
            if (itemType === 'workflow') {
                url += `&workflow_id=${itemId}`;
            } else {
                url += `&prompt_id=${itemId}`;
            }
        }

        if (jobType) url += `&job_type=${jobType}`;

        const response = await fetch(url);
        if (!response.ok) throw new Error('Failed to load jobs');

        const jobs = await response.json();
        importJobsCache = jobs;

        if (jobs.length === 0) {
            document.getElementById('import-job-history-list').innerHTML =
                '<div style="padding: 1rem; text-align: center; color: #64748b;">該当するジョブがありません / No matching jobs</div>';
            return;
        }

        const listHtml = jobs.map(job => {
            const jobTypeLabel = job.is_workflow_job ? 'WF' :
                                 job.job_type === 'single' ? '単発' : 'バッチ';
            const jobPrefix = job.is_workflow_job ? 'WF Job' : 'Job';
            return `
            <div class="job-history-item ${importSelectedJobId === job.id ? 'selected' : ''}"
                 onclick="selectImportJob(${job.id}, ${job.is_workflow_job})">
                <div class="job-history-item-info">
                    <div class="job-history-item-title">${jobPrefix} #${job.id} (${jobTypeLabel})</div>
                    <div class="job-history-item-meta">${job.created_at} | ${job.item_count || 0}件</div>
                </div>
                <span class="job-history-item-status ${job.status}">${job.status}</span>
            </div>
        `}).join('');

        document.getElementById('import-job-history-list').innerHTML = listHtml;

    } catch (error) {
        console.error('Failed to load job history:', error);
        document.getElementById('import-job-history-list').innerHTML =
            `<div style="padding: 1rem; text-align: center; color: #dc2626;">エラー / Error: ${error.message}</div>`;
    }
}

async function selectImportJob(jobId, isWorkflowJob = false) {
    importSelectedJobId = jobId;
    importIsWorkflowJob = isWorkflowJob;
    importHasCsvData = false;  // Reset until we confirm

    // Update selection UI
    document.querySelectorAll('.job-history-item').forEach(item => item.classList.remove('selected'));
    event.currentTarget.classList.add('selected');

    // Load job preview - use appropriate endpoint based on job type
    try {
        const endpoint = isWorkflowJob
            ? `/api/workflow-jobs/${jobId}/csv-preview`
            : `/api/jobs/${jobId}/csv-preview`;
        const response = await fetch(endpoint);
        if (!response.ok) throw new Error('Failed to load preview');

        const preview = await response.json();

        const previewPanel = document.getElementById('import-job-preview');
        const previewContent = document.getElementById('import-job-preview-content');

        if (preview.csv_data) {
            previewContent.textContent = preview.csv_data;
            previewPanel.style.display = 'block';
            importHasCsvData = true;  // CSV data is available
        } else {
            previewContent.textContent = 'CSV出力がありません / No CSV output available';
            previewPanel.style.display = 'block';
            importHasCsvData = false;  // No CSV data
        }

        // Auto-fill dataset name
        const job = importJobsCache.find(j => j.id === jobId);
        const jobPrefix = isWorkflowJob ? 'WF' : 'Job';
        if (job) {
            document.getElementById('import-results-dataset-name').value = `${jobPrefix}_${jobId}_${job.job_type}`;
        }

    } catch (error) {
        console.error('Failed to load job preview:', error);
        document.getElementById('import-job-preview').style.display = 'none';
        importHasCsvData = false;
    }

    // Update import button state
    updateImportButtonState();
}

async function executeDatasetImport() {
    // Determine active tab
    const activeTab = document.querySelector('.import-tab-content.active');
    const tabId = activeTab.id;

    try {
        if (tabId === 'import-tab-excel') {
            await importExcelDataset();
        } else if (tabId === 'import-tab-csv') {
            await importCsvDataset();
        } else if (tabId === 'import-tab-results') {
            await importResultsDataset();
        }
    } catch (error) {
        alert(`エラー / Error: ${error.message}`);
    }
}

async function importExcelDataset() {
    const projectId = document.getElementById('import-excel-project-id').value;
    const mode = document.querySelector('input[name="excel-mode"]:checked').value;
    const rangeName = document.getElementById('import-excel-range-name').value;
    const fileInput = document.getElementById('import-excel-file');

    if (!fileInput.files[0]) {
        throw new Error('Excelファイルを選択してください / Please select an Excel file');
    }

    const formData = new FormData();
    formData.append('project_id', projectId);
    formData.append('range_name', rangeName);
    formData.append('file', fileInput.files[0]);

    if (mode === 'new') {
        const name = document.getElementById('import-excel-dataset-name').value;
        if (!name) throw new Error('データセット名を入力してください / Please enter dataset name');
        formData.append('dataset_name', name);

        const response = await fetch('/api/datasets/import', {
            method: 'POST',
            body: formData
        });
        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.detail || 'Import failed');
        }
    } else {
        const targetDatasetId = document.getElementById('import-excel-target-dataset').value;
        if (!targetDatasetId) throw new Error('追加先のデータセットを選択してください / Please select target dataset');
        formData.append('target_dataset_id', targetDatasetId);

        const response = await fetch('/api/datasets/import/append', {
            method: 'POST',
            body: formData
        });
        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.detail || 'Import failed');
        }
    }

    closeModal();
    await loadDatasets();
    alert('データセットをインポートしました / Dataset imported');
}

async function importCsvDataset() {
    const projectId = document.getElementById('import-csv-project-id').value;
    const mode = document.querySelector('input[name="csv-mode"]:checked').value;
    const encoding = document.getElementById('import-csv-encoding').value;
    const delimiter = document.getElementById('import-csv-delimiter').value;
    const quotechar = document.getElementById('import-csv-quotechar').value;
    const hasHeader = document.getElementById('import-csv-header').value;
    const fileInput = document.getElementById('import-csv-file');

    if (!fileInput.files[0]) {
        throw new Error('CSVファイルを選択してください / Please select a CSV file');
    }

    const formData = new FormData();
    formData.append('project_id', projectId);
    formData.append('encoding', encoding);
    formData.append('delimiter', delimiter);
    formData.append('quotechar', quotechar);
    formData.append('has_header', hasHeader);
    formData.append('file', fileInput.files[0]);

    if (mode === 'new') {
        const name = document.getElementById('import-csv-dataset-name').value;
        if (!name) throw new Error('データセット名を入力してください / Please enter dataset name');
        formData.append('dataset_name', name);
    } else {
        const targetDatasetId = document.getElementById('import-csv-target-dataset').value;
        if (!targetDatasetId) throw new Error('追加先のデータセットを選択してください / Please select target dataset');
        formData.append('target_dataset_id', targetDatasetId);
    }

    const response = await fetch('/api/datasets/import/csv', {
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
}

async function importResultsDataset() {
    if (!importSelectedJobId) {
        throw new Error('ジョブを選択してください / Please select a job');
    }

    const mode = document.querySelector('input[name="results-mode"]:checked').value;
    const projectId = document.getElementById('import-results-project').value;

    const body = {
        job_id: importSelectedJobId,
        project_id: parseInt(projectId)
    };

    if (mode === 'new') {
        const name = document.getElementById('import-results-dataset-name').value;
        if (!name) throw new Error('データセット名を入力してください / Please enter dataset name');
        body.dataset_name = name;
    } else {
        const targetDatasetId = document.getElementById('import-results-target-dataset').value;
        if (!targetDatasetId) throw new Error('追加先のデータセットを選択してください / Please select target dataset');
        body.target_dataset_id = parseInt(targetDatasetId);
    }

    const response = await fetch('/api/datasets/import/from-job', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body)
    });

    if (!response.ok) {
        const error = await response.json();
        throw new Error(error.detail || 'Import failed');
    }

    closeModal();
    await loadDatasets();
    alert('データセットをインポートしました / Dataset imported');
}

async function previewDataset(id, showAll = false) {
    try {
        // Store dataset ID for toggle functionality
        currentPreviewDatasetId = id;

        // Fetch with limit=0 if showAll, otherwise default 10
        const limit = showAll ? 0 : 10;
        const response = await fetch(`/api/datasets/${id}/preview?limit=${limit}`);
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
                            <input type="checkbox" id="preview-show-all" ${showAll ? 'checked' : ''} onchange="togglePreviewShowAll(this.checked)">
                            <span style="font-size: 0.9rem;">全件表示 / Show All</span>
                        </label>
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

/**
 * Toggle show all rows in dataset preview
 * Re-fetches the dataset with all rows or default limit
 */
function togglePreviewShowAll(showAll) {
    if (currentPreviewDatasetId) {
        previewDataset(currentPreviewDatasetId, showAll);
    }
}

// ========== DATASET ROW SELECTION FOR SINGLE EXECUTION ==========

/**
 * Show dataset selector modal for single execution
 * Step 1: User selects a dataset from the list
 */
function showDatasetSelectorForSingle() {
    // Filter datasets for current project
    const projectDatasets = allDatasets.filter(d => d.project_id === currentProjectId);

    if (projectDatasets.length === 0) {
        alert('このプロジェクトにはデータセットがありません。\nバッチ実行タブでデータセットをインポートしてください。\n\nNo datasets for this project.\nPlease import a dataset from the Batch Execution tab.');
        return;
    }

    const datasetListHtml = projectDatasets.map(dataset => `
        <div class="list-item" style="cursor: pointer; padding: 0.75rem; border: 1px solid #ddd; border-radius: 4px; margin-bottom: 0.5rem;"
             onclick="showDatasetRowSelector(${dataset.id})"
             onmouseover="this.style.background='#e8f4fc'"
             onmouseout="this.style.background=''">
            <div style="font-weight: bold;">${dataset.name}</div>
            <div style="font-size: 0.85rem; color: #666;">
                ファイル: ${dataset.source_file_name} | 行数: ${dataset.row_count}
            </div>
        </div>
    `).join('');

    showModal(`
        <div class="modal-header" style="display: flex; justify-content: space-between; align-items: center;">
            <span>データセットを選択 / Select Dataset</span>
            <button onclick="closeModal()" style="background: none; border: none; font-size: 1.5rem; cursor: pointer; color: #7f8c8d; padding: 0 0.5rem;" title="閉じる / Close">×</button>
        </div>
        <div class="modal-body">
            <p style="margin-bottom: 1rem; color: #666;">入力フォームに反映するデータセットを選択してください / Select a dataset to populate the input form</p>
            ${datasetListHtml}
        </div>
        <div class="modal-footer">
            <button class="btn btn-secondary" onclick="closeModal()">キャンセル / Cancel</button>
        </div>
    `);
}

/**
 * Show dataset preview with selectable rows
 * Step 2: User selects a specific row from the dataset
 */
async function showDatasetRowSelector(datasetId, showAll = false) {
    try {
        currentPreviewDatasetId = datasetId;

        const limit = showAll ? 0 : 10;
        const response = await fetch(`/api/datasets/${datasetId}/preview?limit=${limit}`);
        const preview = await response.json();

        function escapeHtml(unsafe) {
            if (unsafe === null || unsafe === undefined) return '';
            return String(unsafe)
                .replace(/&/g, "&amp;")
                .replace(/</g, "&lt;")
                .replace(/>/g, "&gt;")
                .replace(/"/g, "&quot;")
                .replace(/'/g, "&#039;");
        }

        // Create rows with selection capability (store row data as JSON in data attribute)
        const rowsHtml = preview.rows.map((row, index) => {
            const rowDataJson = encodeURIComponent(JSON.stringify(row));
            const cells = preview.columns.map(col => {
                const cellValue = row[col];
                const displayValue = escapeHtml(cellValue) || '';
                const tooltipValue = String(cellValue ?? '').replace(/"/g, '&quot;');
                return `<td title="${tooltipValue}" style="border: 1px solid #ddd; padding: 8px;">${displayValue}</td>`;
            }).join('');
            return `<tr class="selectable-row" data-row="${rowDataJson}" onclick="selectDatasetRow(this)"
                       style="cursor: pointer;"
                       onmouseover="this.style.background='#e8f4fc'"
                       onmouseout="this.style.background=''">${cells}</tr>`;
        }).join('');

        showModal(`
            <div class="modal-header" style="display: flex; justify-content: space-between; align-items: center;">
                <span>行を選択 / Select Row: ${preview.name}</span>
                <button onclick="closeModal()" style="background: none; border: none; font-size: 1.5rem; cursor: pointer; color: #7f8c8d; padding: 0 0.5rem;" title="閉じる / Close">×</button>
            </div>
            <div class="modal-body">
                <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 1rem; flex-wrap: wrap; gap: 0.5rem;">
                    <p style="margin: 0;">総行数 / Total Rows: ${preview.total_count} <span style="color: #666; font-size: 0.9rem;">（クリックで選択 / Click to select）</span></p>
                    <div style="display: flex; gap: 1rem; flex-wrap: wrap;">
                        <label style="display: flex; align-items: center; gap: 0.3rem; cursor: pointer; user-select: none;">
                            <input type="checkbox" id="row-select-show-all" ${showAll ? 'checked' : ''} onchange="toggleRowSelectorShowAll(this.checked)">
                            <span style="font-size: 0.9rem;">全件表示 / Show All</span>
                        </label>
                        <label style="display: flex; align-items: center; gap: 0.3rem; cursor: pointer; user-select: none;">
                            <input type="checkbox" id="row-select-truncate" checked onchange="togglePreviewTruncate(this.checked)">
                            <span style="font-size: 0.9rem;">折り返し省略 / Truncate</span>
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
                <button class="btn btn-secondary" onclick="showDatasetSelectorForSingle()">← 戻る / Back</button>
                <button class="btn btn-secondary" onclick="closeModal()">キャンセル / Cancel</button>
            </div>
        `);

        // Apply default styles
        togglePreviewTruncate(true);
    } catch (error) {
        alert(`エラー / Error: ${error.message}`);
    }
}

/**
 * Toggle show all for row selector
 */
function toggleRowSelectorShowAll(showAll) {
    if (currentPreviewDatasetId) {
        showDatasetRowSelector(currentPreviewDatasetId, showAll);
    }
}

/**
 * Select a row from dataset and populate form
 * Step 3: Populate the input form with selected row data
 */
function selectDatasetRow(rowElement) {
    try {
        const rowDataJson = decodeURIComponent(rowElement.dataset.row);
        const rowData = JSON.parse(rowDataJson);

        // Populate form fields based on parameter names
        currentParameters.forEach(param => {
            const input = document.getElementById(`param-${param.name}`);
            if (input && rowData.hasOwnProperty(param.name)) {
                const value = rowData[param.name];

                // Handle different input types
                if (param.type === 'FILE' || param.type === 'FILEPATH' || param.type === 'TEXTFILEPATH') {
                    // For FILE/FILEPATH/TEXTFILEPATH types, set the value if it's a path string
                    if (typeof value === 'string' && value) {
                        input.value = value;
                    }
                } else if (input.tagName === 'TEXTAREA') {
                    input.value = value ?? '';
                } else if (input.type === 'number') {
                    input.value = value ?? '';
                } else if (input.type === 'date') {
                    // Convert date format if needed
                    if (value) {
                        const date = new Date(value);
                        if (!isNaN(date)) {
                            input.value = date.toISOString().split('T')[0];
                        } else {
                            input.value = value;
                        }
                    }
                } else if (input.type === 'datetime-local') {
                    // Convert datetime format if needed
                    if (value) {
                        const date = new Date(value);
                        if (!isNaN(date)) {
                            input.value = date.toISOString().slice(0, 16);
                        } else {
                            input.value = value;
                        }
                    }
                } else {
                    input.value = value ?? '';
                }
            }
        });

        closeModal();

        // Show success message briefly
        const statusDiv = document.getElementById('execution-status');
        if (statusDiv) {
            statusDiv.textContent = 'データセットから入力を反映しました / Form populated from dataset';
            statusDiv.className = 'status-message success';
            setTimeout(() => {
                statusDiv.textContent = '';
                statusDiv.className = 'status-message';
            }, 3000);
        }
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

function showModal(content, extraClass = '') {
    const modal = document.getElementById('modal-overlay');
    const modalContent = document.getElementById('modal-content');
    if (modal && modalContent) {
        // Remove any previous extra classes
        modalContent.className = 'modal-content';
        if (extraClass) {
            modalContent.classList.add(extraClass);
        }
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

// Track which help tab is active
let currentHelpTab = 'prompt';

/**
 * Unified Help Modal - Shows both Prompt and Parser help with tabbed interface
 */
function showUnifiedHelp() {
    renderUnifiedHelp();
}

function renderUnifiedHelp() {
    const promptTabActive = currentHelpTab === 'prompt';
    const parserTabActive = currentHelpTab === 'parser';

    const promptHelpContent = `
        <h3 style="color: #2c3e50; border-bottom: 2px solid #3498db; padding-bottom: 0.5rem;">📖 プロンプトテンプレート構文 / Prompt Template Syntax</h3>
        <p style="margin: 1rem 0;">
            <code>{{ }}</code> で囲まれた部分がパラメータとして自動的に入力フォームに変換されます。
        </p>

        <h4 style="color: #27ae60; margin-top: 1rem;">基本構文 / Basic Syntax</h4>
        <pre style="background: #f8f9fa; padding: 0.8rem; border-radius: 4px; font-size: 0.9rem;"><code>{{PARAM_NAME:TYPE}}      必須パラメータ / Required
{{PARAM_NAME:TYPE|}}     任意パラメータ / Optional
{{PARAM_NAME:TYPE|default=値}} デフォルト値 / Default value</code></pre>

        <h4 style="color: #27ae60; margin-top: 1rem;">パラメータタイプ / Parameter Types</h4>
        <ul style="margin: 0.5rem 0 1rem 1.5rem; line-height: 1.8;">
            <li><strong>TEXT1〜TEXT20</strong>: テキストエリア（1〜20行）</li>
            <li><strong>NUM</strong>: 数値入力</li>
            <li><strong>DATE / DATETIME</strong>: 日付・日時選択</li>
            <li><strong>FILE</strong>: 画像アップロード（Vision API対応）</li>
            <li><strong>FILEPATH</strong>: サーバー画像パス（バッチ用）</li>
            <li><strong>TEXTFILEPATH</strong>: テキストファイルパス（内容展開）</li>
        </ul>

        <h4 style="color: #27ae60; margin-top: 1rem;">例 / Examples</h4>
        <pre style="background: #f8f9fa; padding: 0.8rem; border-radius: 4px; font-size: 0.85rem; white-space: pre-wrap;"><code>{{name:TEXT1}}           1行テキスト（必須）
{{description:TEXT5}}    5行テキストエリア（必須）
{{age:NUM|}}             数値入力（任意）
{{image:FILE}}           画像アップロード
{{file_path:FILEPATH}}   サーバー画像パス</code></pre>

        <div style="background: #e8f8f5; border-left: 4px solid #27ae60; padding: 0.8rem; margin: 1rem 0;">
            <strong>💡 ヒント:</strong> タイプを省略すると TEXT5（5行テキストエリア、必須）になります
        </div>
    `;

    const parserHelpContent = `
        <h3 style="color: #2c3e50; border-bottom: 2px solid #3498db; padding-bottom: 0.5rem;">📖 パーサー設定 / Parser Configuration</h3>
        <p style="margin: 1rem 0;">
            パーサーはLLMからの生レスポンスを構造化されたデータに変換します。CSV出力に必須です。
        </p>

        <h4 style="color: #27ae60; margin-top: 1rem;">1. JSON Path パーサー (推奨)</h4>
        <pre style="background: #f8f9fa; padding: 0.8rem; border-radius: 4px; font-size: 0.85rem;"><code>{
  "type": "json_path",
  "paths": {
    "answer": "$.answer",
    "score": "$.score"
  },
  "csv_template": "$answer$,$score$"
}</code></pre>

        <h4 style="color: #27ae60; margin-top: 1rem;">2. Regex パーサー</h4>
        <pre style="background: #f8f9fa; padding: 0.8rem; border-radius: 4px; font-size: 0.85rem;"><code>{
  "type": "regex",
  "patterns": {
    "answer": "Answer: (.+)",
    "score": "Score: (\\\\d+)"
  },
  "csv_template": "$answer$,$score$"
}</code></pre>

        <h4 style="color: #27ae60; margin-top: 1rem;">CSV出力設定</h4>
        <ul style="margin: 0.5rem 0 1rem 1.5rem; line-height: 1.8;">
            <li><code>csv_template</code>: CSV行の形式を指定</li>
            <li><code>$フィールド名$</code> の形式でフィールドを参照</li>
            <li>バッチ実行時に全結果がCSV形式に結合されます</li>
        </ul>

        <div style="background: #e8f8f5; border-left: 4px solid #27ae60; padding: 0.8rem; margin: 1rem 0;">
            <strong>💡 ヒント:</strong> プロンプトでLLMにJSON形式での出力を指示すると、パース精度が向上します
        </div>

        <div style="background: #fff3cd; border-left: 4px solid #ffc107; padding: 0.8rem; margin: 1rem 0;">
            <strong>⚠️ 注意:</strong> フィールド名は paths と csv_template で一致させてください
        </div>
    `;

    const helpContent = `
        <div class="modal-header" style="display: flex; justify-content: space-between; align-items: center;">
            <span style="font-weight: bold;">ヘルプ / Help</span>
            <button class="btn btn-secondary" onclick="closeModal2()" style="margin: 0; padding: 5px 15px;">閉じる / Close</button>
        </div>
        <div class="modal-body" style="max-height: 65vh; overflow-y: auto;">
            <!-- Tab Navigation -->
            <div style="display: flex; gap: 0; margin-bottom: 15px; border-bottom: 2px solid #007bff;">
                <button onclick="switchHelpTab('prompt')"
                    style="padding: 8px 20px; border: none; background: ${promptTabActive ? '#007bff' : '#e9ecef'}; color: ${promptTabActive ? 'white' : '#333'}; cursor: pointer; border-radius: 5px 5px 0 0; font-weight: ${promptTabActive ? 'bold' : 'normal'};">
                    プロンプト構文 / Prompt
                </button>
                <button onclick="switchHelpTab('parser')"
                    style="padding: 8px 20px; border: none; background: ${parserTabActive ? '#007bff' : '#e9ecef'}; color: ${parserTabActive ? 'white' : '#333'}; cursor: pointer; border-radius: 5px 5px 0 0; font-weight: ${parserTabActive ? 'bold' : 'normal'};">
                    パーサー設定 / Parser
                </button>
            </div>

            <!-- Help Content -->
            <div id="help-tab-content" style="min-height: 350px;">
                ${promptTabActive ? promptHelpContent : parserHelpContent}
            </div>
        </div>
    `;
    showModal2(helpContent);
}

function switchHelpTab(tab) {
    currentHelpTab = tab;
    renderUnifiedHelp();
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
                <li><strong>FILEPATH</strong>: サーバー画像ファイルパス（バッチ処理用）/ Server image file path (for batch processing)
                    <ul style="margin-top: 0.3rem;">
                        <li>サーバー上の画像ファイルパスを指定 / Specify image file path on server</li>
                        <li>バッチ実行時、データセットにファイルパスを記載して使用 / Use by specifying file paths in dataset for batch execution</li>
                    </ul>
                </li>
                <li><strong>TEXTFILEPATH</strong>: テキストファイルパス（内容をプロンプトに埋め込み）/ Text file path (content embedded in prompt)
                    <ul style="margin-top: 0.3rem;">
                        <li>サーバー上のテキストファイルパスを指定 / Specify text file path on server</li>
                        <li>ファイルの内容を読み込んでプロンプト本文に展開 / File content is read and embedded in prompt</li>
                        <li>UTF-8エンコーディングに対応 / Supports UTF-8 encoding</li>
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

            <h3 id="role-markers" style="color: #2c3e50; border-bottom: 2px solid #9b59b6; padding-bottom: 0.5rem; margin-top: 2rem;">🎭 ロールマーカー / Role Markers</h3>
            <p style="margin: 1rem 0;">
                ロールマーカーを使うと、LLM APIに送信するメッセージの役割（system/user/assistant）を明示的に指定できます。<br>
                Role markers allow you to explicitly specify message roles (system/user/assistant) sent to the LLM API.
            </p>

            <h4 style="color: #9b59b6; margin-top: 1rem;">マーカーの種類 / Marker Types</h4>
            <table style="width: 100%; border-collapse: collapse; margin: 1rem 0;">
                <thead>
                    <tr style="background: #f8f9fa;">
                        <th style="padding: 0.5rem; border: 1px solid #ddd; text-align: left;">マーカー / Marker</th>
                        <th style="padding: 0.5rem; border: 1px solid #ddd; text-align: left;">役割 / Role</th>
                        <th style="padding: 0.5rem; border: 1px solid #ddd; text-align: left;">用途 / Usage</th>
                    </tr>
                </thead>
                <tbody>
                    <tr>
                        <td style="padding: 0.5rem; border: 1px solid #ddd;"><code style="background: #fff3cd; padding: 2px 6px; border-radius: 3px;">[SYSTEM]</code></td>
                        <td style="padding: 0.5rem; border: 1px solid #ddd;">システム指示</td>
                        <td style="padding: 0.5rem; border: 1px solid #ddd;">AIの振る舞い・ペルソナ設定（<strong>1つのみ</strong>）</td>
                    </tr>
                    <tr>
                        <td style="padding: 0.5rem; border: 1px solid #ddd;"><code style="background: #d4edda; padding: 2px 6px; border-radius: 3px;">[USER]</code></td>
                        <td style="padding: 0.5rem; border: 1px solid #ddd;">ユーザー入力</td>
                        <td style="padding: 0.5rem; border: 1px solid #ddd;">質問・リクエスト・入力データ（複数可）</td>
                    </tr>
                    <tr>
                        <td style="padding: 0.5rem; border: 1px solid #ddd;"><code style="background: #d1ecf1; padding: 2px 6px; border-radius: 3px;">[ASSISTANT]</code></td>
                        <td style="padding: 0.5rem; border: 1px solid #ddd;">アシスタント応答</td>
                        <td style="padding: 0.5rem; border: 1px solid #ddd;">Few-shot例・会話履歴（複数可）</td>
                    </tr>
                </tbody>
            </table>

            <h4 style="color: #9b59b6; margin-top: 1rem;">使用例1: 基本パターン / Example 1: Basic Pattern</h4>
            <pre style="background: #f8f9fa; padding: 1rem; border-radius: 4px; overflow-x: auto; white-space: pre-wrap;"><code>[SYSTEM]
あなたは日本語翻訳の専門家です。丁寧で自然な日本語に翻訳してください。

[USER]
次のテキストを翻訳してください：
{{TEXT_TO_TRANSLATE}}</code></pre>

            <h4 style="color: #9b59b6; margin-top: 1rem;">使用例2: Few-shot学習 / Example 2: Few-shot Learning</h4>
            <pre style="background: #f8f9fa; padding: 1rem; border-radius: 4px; overflow-x: auto; white-space: pre-wrap;"><code>[SYSTEM]
質問に簡潔に回答してください。

[USER]
東京の人口は？

[ASSISTANT]
約1400万人です。

[USER]
{{QUESTION}}</code></pre>

            <div style="background: #fdf2f8; border-left: 4px solid #9b59b6; padding: 1rem; margin: 1.5rem 0;">
                <strong>⚠️ ロールマーカーの注意事項 / Role Marker Notes:</strong>
                <ul style="margin: 0.5rem 0 0 1.5rem;">
                    <li><strong>[SYSTEM] は1つだけ</strong>：複数あるとエラーになります / Only one [SYSTEM] allowed</li>
                    <li><strong>マーカーがない場合</strong>：全文が [USER] として送信されます（従来通り）/ Without markers, entire text sent as [USER]</li>
                    <li><strong>大文字小文字不問</strong>：[SYSTEM], [System], [system] 全て有効 / Case insensitive</li>
                    <li><strong>{{}}パラメータと併用可</strong>：各セクション内で通常通り使用可能 / Can use {{}} parameters in each section</li>
                </ul>
            </div>

            <h3 id="parser-config" style="color: #2c3e50; border-bottom: 2px solid #e67e22; padding-bottom: 0.5rem; margin-top: 2rem;">🔧 パーサー設定 / Parser Configuration</h3>
            <p style="margin: 1rem 0;">
                パーサーは、LLMからの生レスポンスを構造化されたデータに変換します。CSV出力には必須です。<br>
                The parser converts raw LLM responses into structured data. Required for CSV output.
            </p>

            <h4 style="color: #e67e22; margin-top: 1rem;">JSON Path パーサー (推奨 / Recommended)</h4>
            <p><strong>用途:</strong> LLMがJSON形式で返答する場合</p>
            <pre style="background: #f8f9fa; padding: 1rem; border-radius: 4px; overflow-x: auto;"><code>{
  "type": "json_path",
  "paths": {
    "answer": "$.answer",
    "confidence": "$.confidence"
  },
  "csv_template": "$answer$,$confidence$"
}</code></pre>

            <h4 style="color: #e67e22; margin-top: 1rem;">Regex パーサー</h4>
            <p><strong>用途:</strong> LLMがテキスト形式で返答する場合</p>
            <pre style="background: #f8f9fa; padding: 1rem; border-radius: 4px; overflow-x: auto;"><code>{
  "type": "regex",
  "patterns": {
    "answer": "Answer: (.+)",
    "score": "Score: (\\\\d+)"
  },
  "csv_template": "$answer$,$score$"
}</code></pre>

            <h4 style="color: #e67e22; margin-top: 1rem;">CSV Template パーサー</h4>
            <p><strong>用途:</strong> JSON Pathで抽出した値をCSV形式に変換</p>
            <pre style="background: #f8f9fa; padding: 1rem; border-radius: 4px; overflow-x: auto;"><code>{
  "type": "csv_template",
  "paths": {
    "product": "$.product_name",
    "price": "$.price",
    "rating": "$.rating"
  },
  "csv_template": "$product$,$price$,$rating$"
}</code></pre>

            <div style="background: #fff3e6; border-left: 4px solid #e67e22; padding: 1rem; margin: 1.5rem 0;">
                <strong>💡 パーサー設定のヒント / Parser Tips:</strong>
                <ul style="margin: 0.5rem 0 0 1.5rem;">
                    <li><code>$フィールド名$</code> 形式でCSV列を指定</li>
                    <li>JSON Pathは <code>$.</code> で始まる（例: <code>$.answer</code>）</li>
                    <li>バッチ実行時、全結果が自動的にCSVに結合されます</li>
                    <li>「CSVヘッダを含める」でヘッダー行を追加</li>
                </ul>
            </div>

            <h3 id="workflow-variables" style="color: #2c3e50; border-bottom: 2px solid #16a085; padding-bottom: 0.5rem; margin-top: 2rem;">🔗 ワークフロー変数 / Workflow Variables</h3>
            <p style="margin: 1rem 0;">
                ワークフローでは、前のステップの出力を次のステップで参照できます。<br>
                In workflows, you can reference output from previous steps in subsequent steps.
            </p>

            <h4 style="color: #16a085; margin-top: 1rem;">基本参照 / Basic References</h4>
            <table style="width: 100%; border-collapse: collapse; margin: 1rem 0;">
                <thead>
                    <tr style="background: #f8f9fa;">
                        <th style="padding: 0.5rem; border: 1px solid #ddd; text-align: left;">変数 / Variable</th>
                        <th style="padding: 0.5rem; border: 1px solid #ddd; text-align: left;">説明 / Description</th>
                    </tr>
                </thead>
                <tbody>
                    <tr>
                        <td style="padding: 0.5rem; border: 1px solid #ddd;"><code>{{input.param}}</code></td>
                        <td style="padding: 0.5rem; border: 1px solid #ddd;">初期入力パラメータ</td>
                    </tr>
                    <tr>
                        <td style="padding: 0.5rem; border: 1px solid #ddd;"><code>{{step1.field}}</code></td>
                        <td style="padding: 0.5rem; border: 1px solid #ddd;">ステップ出力フィールド（パーサーで抽出）</td>
                    </tr>
                    <tr>
                        <td style="padding: 0.5rem; border: 1px solid #ddd;"><code>{{step1.raw}}</code></td>
                        <td style="padding: 0.5rem; border: 1px solid #ddd;">生のLLM出力</td>
                    </tr>
                </tbody>
            </table>

            <h4 style="color: #16a085; margin-top: 1rem;">ロール変数 / Role Variables</h4>
            <p>各ステップのプロンプト内容とLLM応答を参照できます：</p>
            <table style="width: 100%; border-collapse: collapse; margin: 1rem 0;">
                <thead>
                    <tr style="background: #f8f9fa;">
                        <th style="padding: 0.5rem; border: 1px solid #ddd; text-align: left;">変数 / Variable</th>
                        <th style="padding: 0.5rem; border: 1px solid #ddd; text-align: left;">説明 / Description</th>
                    </tr>
                </thead>
                <tbody>
                    <tr>
                        <td style="padding: 0.5rem; border: 1px solid #ddd;"><code style="background: #fff3cd;">{{step1.SYSTEM}}</code></td>
                        <td style="padding: 0.5rem; border: 1px solid #ddd;">ステップのシステムメッセージ</td>
                    </tr>
                    <tr>
                        <td style="padding: 0.5rem; border: 1px solid #ddd;"><code style="background: #d4edda;">{{step1.USER}}</code></td>
                        <td style="padding: 0.5rem; border: 1px solid #ddd;">ステップのユーザーメッセージ</td>
                    </tr>
                    <tr>
                        <td style="padding: 0.5rem; border: 1px solid #ddd;"><code style="background: #d1ecf1;">{{step1.ASSISTANT}}</code></td>
                        <td style="padding: 0.5rem; border: 1px solid #ddd;">ステップのLLM応答</td>
                    </tr>
                    <tr>
                        <td style="padding: 0.5rem; border: 1px solid #ddd;"><code style="background: #e2d5f1;">{{step1.CONTEXT}}</code></td>
                        <td style="padding: 0.5rem; border: 1px solid #ddd;">それまでの全会話履歴（USER/ASSISTANT）</td>
                    </tr>
                </tbody>
            </table>

            <h4 style="color: #16a085; margin-top: 1rem;">CONTEXTの使用例 / CONTEXT Usage Example</h4>
            <pre style="background: #f8f9fa; padding: 1rem; border-radius: 4px; overflow-x: auto; white-space: pre-wrap;"><code>[SYSTEM]
あなたは会話を継続するアシスタントです。

{{step2.CONTEXT}}

[USER]
{{NEW_QUESTION}}</code></pre>
            <p style="margin: 0.5rem 0; color: #555;">
                <code>CONTEXT</code> は過去のUSER/ASSISTANTを全て含むため、マルチターン会話を簡単に実現できます。
            </p>

            <div style="background: #e8f6f3; border-left: 4px solid #16a085; padding: 1rem; margin: 1.5rem 0;">
                <strong>💡 ワークフロー変数のヒント / Workflow Variable Tips:</strong>
                <ul style="margin: 0.5rem 0 0 1.5rem;">
                    <li>変数ピッカー（🔗ボタン）で利用可能な変数を確認できます</li>
                    <li><code>CONTEXT</code> を使えば会話履歴を自動的に引き継げます</li>
                    <li>パーサーで抽出したフィールドも <code>{{step.field}}</code> で参照可能</li>
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

        // Load tags for tag management
        await loadTagsManagement();

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
            select.innerHTML = availableModelsData.map(m => {
                const privateIcon = m.is_private ? '\u{1F512} ' : '';
                return `<option value="${m.name}">${privateIcon}${m.display_name}</option>`;
            }).join('');
        }
    });

    // Display available models list in settings
    const availableModelsDiv = document.getElementById('available-models');
    if (availableModelsDiv) {
        availableModelsDiv.innerHTML = `
            <ul>
                ${availableModelsData.map(m => {
                    const privateIcon = m.is_private ? '<span style="color: #e67e22;" title="Private Model">&#128274;</span> ' : '';
                    return `<li>${privateIcon}${m.display_name} (${m.name})</li>`;
                }).join('')}
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
// Text File Extensions Setting
// ========================================

async function loadTextFileExtensions() {
    try {
        const response = await fetch('/api/settings/text-file-extensions');
        if (!response.ok) throw new Error('Failed to load text file extensions');

        const data = await response.json();
        document.getElementById('text-file-extensions').value = data.extensions || '';

    } catch (error) {
        console.error('Failed to load text file extensions:', error);
    }
}

async function saveTextFileExtensions() {
    const extensions = document.getElementById('text-file-extensions').value;
    const statusEl = document.getElementById('text-extensions-status');

    try {
        const response = await fetch(`/api/settings/text-file-extensions?extensions=${encodeURIComponent(extensions)}`, {
            method: 'PUT'
        });

        if (!response.ok) throw new Error('Failed to save text file extensions');

        const data = await response.json();
        document.getElementById('text-file-extensions').value = data.extensions;

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

async function resetTextFileExtensions() {
    const statusEl = document.getElementById('text-extensions-status');

    try {
        const response = await fetch('/api/settings/text-file-extensions', {
            method: 'DELETE'
        });

        if (!response.ok) throw new Error('Failed to reset text file extensions');

        const data = await response.json();
        document.getElementById('text-file-extensions').value = data.extensions;

        statusEl.textContent = 'デフォルトにリセットしました / Reset to default';
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

/**
 * Delete/cancel a job from the history list (trash icon click)
 * @param {number} jobId - Job ID to delete
 * @param {string} jobType - 'single' or 'batch'
 */
async function deleteJob(jobId, jobType) {
    if (!confirm(`Job #${jobId} を削除しますか？\nDelete Job #${jobId}?`)) {
        return;
    }

    try {
        const response = await fetch(`/api/jobs/${jobId}/cancel`, {
            method: 'POST'
        });

        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.detail || 'Failed to delete job');
        }

        const data = await response.json();

        // Show success message
        showStatus(
            `Job #${jobId} を削除しました (${data.cancelled_count}件キャンセル) / Job #${jobId} deleted (${data.cancelled_count} items cancelled)`,
            'success'
        );

        // Reload the appropriate history
        if (jobType === 'single') {
            await loadConfig();  // Reloads single job history
        } else if (jobType === 'batch') {
            const projectSelect = document.getElementById('batch-project-select');
            if (projectSelect && projectSelect.value) {
                const parsed = parseSelectValue(projectSelect.value);
                if (parsed && parsed.id) {
                    await loadBatchJobHistory(parsed.id);
                }
            }
        }

    } catch (error) {
        console.error('Error deleting job:', error);
        showStatus(`削除エラー / Delete Error: ${error.message}`, 'error');
    }
}

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
    const selectValue = document.getElementById('batch-project-select')?.value;
    const parsed = parseSelectValue(selectValue);
    const projectId = parsed?.id;

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
            await loadBatchJobHistory(projectId);
        } catch (error) {
            console.error('Error reloading job after cancel:', error);
        }
    }
}

/**
 * Toggle inline JSON to CSV converter section visibility
 * @param {string} suffix - Optional suffix for element IDs (e.g., '-workflow' for workflow editor)
 */
function toggleJsonCsvConverter(suffix = '') {
    const section = document.getElementById('json-csv-converter-section' + suffix);
    const toggleBtn = document.getElementById('json-csv-toggle-btn' + suffix);

    if (!section) {
        console.warn('toggleJsonCsvConverter: section not found with suffix:', suffix);
        return;
    }

    if (section.style.display === 'none' || section.style.display === '') {
        section.style.display = 'block';
        if (toggleBtn) {
            toggleBtn.style.background = '#9b59b6';
            toggleBtn.style.color = 'white';
            toggleBtn.textContent = 'JSON→CSV ▼';
        }
    } else {
        section.style.display = 'none';
        if (toggleBtn) {
            toggleBtn.style.background = 'transparent';
            toggleBtn.style.color = '#9b59b6';
            toggleBtn.textContent = 'JSON→CSV';
        }
    }
}

/**
 * Convert JSON to CSV template inline (within parser tab)
 * @param {string} suffix - Optional suffix for element IDs (e.g., '-workflow' for workflow editor)
 */
function convertJsonToCsvTemplateInline(suffix = '') {
    const jsonInput = document.getElementById('json-sample-input' + suffix);
    const outputArea = document.getElementById('generated-parser-config-inline' + suffix);
    const headerPreview = document.getElementById('csv-header-preview-inline' + suffix);

    if (!jsonInput || !jsonInput.value.trim()) {
        alert('JSONを入力してください / Please enter JSON');
        return;
    }

    try {
        // Remove <...> placeholders and replace with sample values for parsing
        let cleanedJson = jsonInput.value.trim()
            .replace(/"<[^>]+>"/g, '"sample"')
            .replace(/<[^>]+>/g, '"sample"')
            .replace(/,\s*}/g, '}')
            .replace(/,\s*]/g, ']');

        const jsonData = JSON.parse(cleanedJson);

        // Extract all leaf paths
        const paths = {};
        const fieldNames = [];
        extractPaths(jsonData, '$', paths, fieldNames);

        // Generate CSV template with double quotes around each field
        const csvTemplate = fieldNames.map(name => '"$' + name + '$"').join(',');

        // Generate parser config
        const parserConfig = {
            type: 'json_path',
            paths: paths,
            csv_template: csvTemplate
        };

        if (outputArea) outputArea.value = JSON.stringify(parserConfig, null, 2);
        if (headerPreview) headerPreview.value = fieldNames.join(',');

    } catch (error) {
        alert('JSONの解析に失敗しました / Failed to parse JSON: ' + error.message);
        if (outputArea) outputArea.value = 'Error: ' + error.message;
        if (headerPreview) headerPreview.value = '';
    }
}

/**
 * Apply generated parser config inline (within parser tab)
 * @param {string} suffix - Optional suffix for element IDs (e.g., '-workflow' for workflow editor)
 * @param {string} targetConfigId - ID of the target parser config textarea
 * @param {string} targetTypeId - ID of the target parser type select
 */
function applyGeneratedParserConfigInline(suffix = '', targetConfigId = '', targetTypeId = '') {
    const generatedConfigEl = document.getElementById('generated-parser-config-inline' + suffix);
    const generatedConfig = generatedConfigEl ? generatedConfigEl.value : '';

    if (!generatedConfig || generatedConfig.startsWith('Error:')) {
        alert('有効なパーサー設定がありません / No valid parser config available');
        return;
    }

    try {
        // Validate JSON
        const config = JSON.parse(generatedConfig);

        // Determine target elements based on suffix or explicit IDs
        let mainConfigArea, parserTypeSelect;

        if (targetConfigId) {
            mainConfigArea = document.getElementById(targetConfigId);
            parserTypeSelect = document.getElementById(targetTypeId);
        } else if (suffix === '-workflow') {
            mainConfigArea = document.getElementById('prompt-editor-parser-config');
            parserTypeSelect = document.getElementById('prompt-editor-parser-type');
        } else {
            // Try modal parser config first (edit-parser-config)
            mainConfigArea = document.getElementById('edit-parser-config');
            parserTypeSelect = document.getElementById('edit-parser-type');
        }

        if (mainConfigArea) {
            mainConfigArea.value = generatedConfig;
            if (parserTypeSelect) {
                parserTypeSelect.value = config.type || 'json_path';
            }
        }

        // Hide the converter section
        toggleJsonCsvConverter(suffix);

        alert('パーサー設定に適用しました。保存ボタンで保存してください。\n\nApplied to parser config. Click Save to save.');

    } catch (error) {
        alert('パーサー設定の適用に失敗しました / Failed to apply parser config: ' + error.message);
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

        // Generate CSV template with double quotes around each field
        // Quotes in template ensure proper CSV escaping for values with commas, quotes, etc.
        const csvTemplate = fieldNames.map(name => '"$' + name + '$"').join(',');

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

// ========================================
// Workflow Functions (v2.0)
// ========================================

/**
 * Global HTML escape function for workflow code
 */
function escapeHtmlGlobal(unsafe) {
    if (unsafe === null || unsafe === undefined) return '';
    return String(unsafe)
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#039;");
}

/** Get icon for step type in execution trace */
function getStepTypeIcon(stepType) {
    const icons = {
        'prompt': '📝',
        'set': '📦',
        'if': '🔀',
        'elif': '🔀',
        'else': '🔀',
        'endif': '🔀',
        'loop': '🔄',
        'endloop': '🔄',
        'foreach': '🔁',
        'endforeach': '🔁',
        'break': '⏹',
        'continue': '⏭'
    };
    return icons[stepType] || '❓';
}

/** Get CSS class for action type in execution trace */
function getActionClass(action) {
    if (action.includes('taken') || action.includes('executed') || action.includes('enter') || action.includes('start')) {
        return 'trace-action-success';
    } else if (action.includes('skipped') || action.includes('exit') || action.includes('complete')) {
        return 'trace-action-skip';
    } else if (action.includes('break')) {
        return 'trace-action-break';
    } else if (action.includes('continue') || action.includes('next')) {
        return 'trace-action-continue';
    }
    return 'trace-action-default';
}

/** Get display label for action in execution trace */
function getActionLabel(action) {
    const labels = {
        'executed': '実行',
        'branch_taken': '✓ 条件成立',
        'branch_skipped': '✗ 条件不成立',
        'skipped': 'スキップ',
        'loop_enter': '→ ループ開始',
        'loop_exit': '← ループ終了',
        'loop_continue': '↩ 次のイテレーション',
        'foreach_start': '→ FOREACH開始',
        'foreach_skip': 'スキップ (空リスト)',
        'foreach_next': '↩ 次の要素',
        'foreach_complete': '✓ FOREACH完了',
        'break_loop': '⏹ LOOPを脱出',
        'break_foreach': '⏹ FOREACHを脱出',
        'break_no_loop': '⚠ ループ外',
        'continue_loop': '⏭ ENDLOOP へ',
        'continue_foreach': '⏭ ENDFOREACH へ',
        'continue_no_loop': '⚠ ループ外'
    };
    return labels[action] || action;
}

/** Global state for workflows */
let workflows = [];
let selectedWorkflow = null;
let workflowStepCounter = 0;
let selectedWorkflowProjectId = null;

/**
 * Initialize workflow tab - populate project selector
 */
async function initWorkflowTab() {
    try {
        // Load projects if not already loaded
        if (!allProjects || allProjects.length === 0) {
            await loadProjects();
        }

        const select = document.getElementById('workflow-project-select');
        if (!select) return;

        // Populate project options
        select.innerHTML = '<option value="">-- プロジェクトを選択 / Select Project --</option>' +
            allProjects.map(p => `<option value="${p.id}">${escapeHtmlGlobal(p.name)}</option>`).join('');

        // Clear workflow list until project is selected
        const list = document.getElementById('workflow-list');
        if (list) {
            list.innerHTML = '<div class="empty-message">プロジェクトを選択してください<br>Please select a project</div>';
        }
    } catch (error) {
        console.error('Error initializing workflow tab:', error);
    }
}

/**
 * Handle workflow project selection change
 */
async function onWorkflowProjectChange() {
    const select = document.getElementById('workflow-project-select');
    const createBtn = document.getElementById('btn-create-workflow');
    const hint = document.getElementById('workflow-project-hint');

    selectedWorkflowProjectId = select.value ? parseInt(select.value) : null;
    console.log('[onWorkflowProjectChange] selectedWorkflowProjectId:', selectedWorkflowProjectId);

    if (selectedWorkflowProjectId) {
        createBtn.disabled = false;
        if (hint) hint.style.display = 'none';
        console.log('[onWorkflowProjectChange] Calling loadWorkflows()');
        await loadWorkflows();
    } else {
        createBtn.disabled = true;
        if (hint) hint.style.display = '';
        const list = document.getElementById('workflow-list');
        if (list) {
            list.innerHTML = '<div class="empty-message">プロジェクトを選択してください<br>Please select a project</div>';
        }
    }

    // Hide any open editors
    hideWorkflowEditor();
}

/**
 * Load and display workflow list (filtered by selected project)
 */
async function loadWorkflows() {
    try {
        // Build URL with project filter
        let url = '/api/workflows';
        if (selectedWorkflowProjectId) {
            url += `?project_id=${selectedWorkflowProjectId}`;
        }
        console.log('[loadWorkflows] Fetching from:', url, 'selectedWorkflowProjectId:', selectedWorkflowProjectId);

        const response = await fetch(url);
        if (!response.ok) throw new Error('Failed to load workflows');
        workflows = await response.json();
        console.log('[loadWorkflows] Received workflows:', workflows.length, workflows.map(w => ({id: w.id, name: w.name, project_id: w.project_id})));

        const list = document.getElementById('workflow-list');
        if (!list) {
            console.error('[loadWorkflows] workflow-list element not found!');
            return;
        }

        if (workflows.length === 0) {
            list.innerHTML = '<div class="empty-message">ワークフローがありません<br>No workflows yet</div>';
            return;
        }

        list.innerHTML = workflows.map(w => `
            <div class="workflow-item ${selectedWorkflow && selectedWorkflow.id === w.id ? 'selected' : ''}"
                 onclick="selectWorkflow(${w.id})">
                <div class="workflow-name">${escapeHtmlGlobal(w.name)}</div>
                <div class="workflow-info">${w.steps.length} ステップ / steps</div>
            </div>
        `).join('');
        console.log('[loadWorkflows] Rendered', workflows.length, 'workflow items');

    } catch (error) {
        console.error('Error loading workflows:', error);
    }
}

/**
 * Show workflow editor for creating new workflow
 */
function showCreateWorkflowForm() {
    selectedWorkflow = null;
    workflowStepCounter = 0;

    document.getElementById('workflow-editor-title').textContent = 'ワークフロー作成 / Create Workflow';
    document.getElementById('workflow-editor-id-info').textContent = '';
    document.getElementById('workflow-id').value = '';
    document.getElementById('workflow-name').value = '';
    document.getElementById('workflow-description').value = '';
    document.getElementById('workflow-auto-context').checked = false;
    document.getElementById('workflow-steps-container').innerHTML = '';

    document.getElementById('workflow-editor').style.display = 'block';

    // Hide Save As, Export, and Delete buttons for new workflow
    document.getElementById('btn-workflow-save-as').style.display = 'none';
    document.getElementById('btn-workflow-export').style.display = 'none';
    document.getElementById('btn-workflow-delete').style.display = 'none';

    // Deselect in list
    document.querySelectorAll('.workflow-item').forEach(el => el.classList.remove('selected'));
}

/**
 * Hide workflow editor
 */
function hideWorkflowEditor() {
    document.getElementById('workflow-editor').style.display = 'none';
}

/**
 * Add a step to the workflow form
 */
async function addWorkflowStep(stepData = null) {
    workflowStepCounter++;
    const stepNumber = workflowStepCounter;

    // Load projects for dropdown if not already loaded
    if (!allProjects || allProjects.length === 0) {
        await loadProjects();
    }

    const container = document.getElementById('workflow-steps-container');
    const stepDiv = document.createElement('div');
    stepDiv.className = 'workflow-step';
    stepDiv.id = `workflow-step-${stepNumber}`;
    stepDiv.dataset.stepId = stepData ? stepData.id : '';

    // Determine step type (default to 'prompt' for backward compatibility)
    const stepType = stepData?.step_type || 'prompt';
    const conditionConfig = stepData?.condition_config || {};

    // Determine default project ID: use stepData.project_id if editing,
    // otherwise use workflow's project (selectedWorkflowProjectId), fallback to currentProjectId
    const defaultProjectId = stepData ? stepData.project_id : (selectedWorkflowProjectId || currentProjectId);

    const projectOptions = allProjects.map(p =>
        `<option value="${p.id}" ${defaultProjectId && defaultProjectId === p.id ? 'selected' : ''}>${escapeHtmlGlobal(p.name)}</option>`
    ).join('');

    // Step type options
    const stepTypeOptions = [
        { value: 'prompt', label: 'プロンプト実行', icon: '📝' },
        { value: 'set', label: '変数設定 (SET)', icon: '📦' },
        { value: 'if', label: '条件分岐 (IF)', icon: '🔀' },
        { value: 'elif', label: '条件分岐 (ELIF)', icon: '🔀' },
        { value: 'else', label: '条件分岐 (ELSE)', icon: '🔀' },
        { value: 'endif', label: '条件分岐終了 (ENDIF)', icon: '🔀' },
        { value: 'loop', label: 'ループ開始 (LOOP)', icon: '🔄' },
        { value: 'endloop', label: 'ループ終了 (ENDLOOP)', icon: '🔄' },
        { value: 'foreach', label: 'リスト展開 (FOREACH)', icon: '🔄' },
        { value: 'endforeach', label: 'リスト展開終了 (ENDFOREACH)', icon: '🔄' },
        { value: 'break', label: 'ループ脱出 (BREAK)', icon: '⏹' },
        { value: 'continue', label: '次のループへ (CONTINUE)', icon: '⏭' }
    ].map(opt =>
        `<option value="${opt.value}" ${stepType === opt.value ? 'selected' : ''}>${opt.icon} ${opt.label}</option>`
    ).join('');

    // Build condition config values for different step types
    const setAssignments = conditionConfig.assignments || {};
    const conditionLeft = conditionConfig.left || '';
    const conditionRight = conditionConfig.right || '';
    const conditionOperator = conditionConfig.operator || '==';
    const maxIterations = conditionConfig.max_iterations || 10;
    const foreachSource = conditionConfig.source || '';
    const foreachItemVar = conditionConfig.item_var || 'item';
    const foreachIndexVar = conditionConfig.index_var || 'i';

    // Build SET assignments HTML
    let setAssignmentsHtml = '';
    const assignmentEntries = Object.entries(setAssignments);
    if (assignmentEntries.length === 0) {
        setAssignmentsHtml = `
            <div class="set-assignment-row">
                <div class="input-with-var-btn" style="display: flex; gap: 4px;">
                    <input type="text" class="set-var-name" placeholder="変数名" value="">
                    <button type="button" class="btn-var-insert" onclick="showVariablePicker(this)" title="変数を挿入 / Insert Variable">{...}</button>
                </div>
                <span>=</span>
                <div class="input-with-var-btn" style="flex: 1; display: flex; gap: 4px;">
                    <input type="text" class="set-var-value" placeholder="値 ({{step.field}} も使用可)" value="" style="flex: 1;">
                    <button type="button" class="btn-var-insert" onclick="showVariablePicker(this)" title="変数を挿入 / Insert Variable">{...}</button>
                </div>
                <button type="button" class="btn btn-danger btn-sm" onclick="removeSetAssignment(this)">✕</button>
            </div>
        `;
    } else {
        for (const [varName, varValue] of assignmentEntries) {
            setAssignmentsHtml += `
                <div class="set-assignment-row">
                    <div class="input-with-var-btn" style="display: flex; gap: 4px;">
                        <input type="text" class="set-var-name" placeholder="変数名" value="${escapeHtmlGlobal(varName)}">
                        <button type="button" class="btn-var-insert" onclick="showVariablePicker(this)" title="変数を挿入 / Insert Variable">{...}</button>
                    </div>
                    <span>=</span>
                    <div class="input-with-var-btn" style="flex: 1; display: flex; gap: 4px;">
                        <input type="text" class="set-var-value" placeholder="値 ({{step.field}} も使用可)" value="${escapeHtmlGlobal(varValue)}" style="flex: 1;">
                        <button type="button" class="btn-var-insert" onclick="showVariablePicker(this)" title="変数を挿入 / Insert Variable">{...}</button>
                    </div>
                    <button type="button" class="btn btn-danger btn-sm" onclick="removeSetAssignment(this)">✕</button>
                </div>
            `;
        }
    }

    // Get initial step name and type for display in collapsed header
    const initialStepName = stepData ? escapeHtmlGlobal(stepData.step_name) : 'step' + stepNumber;
    const stepTypeLabels = {
        'prompt': '📝 プロンプト',
        'set': '📦 SET',
        'if': '🔀 IF',
        'elif': '🔀 ELIF',
        'else': '🔀 ELSE',
        'endif': '🔀 ENDIF',
        'loop': '🔄 LOOP',
        'endloop': '🔄 ENDLOOP',
        'foreach': '🔄 FOREACH',
        'endforeach': '🔄 ENDFOREACH',
        'break': '⏹ BREAK',
        'continue': '⏭ CONTINUE'
    };
    const stepTypeLabel = stepTypeLabels[stepType] || stepType;

    stepDiv.innerHTML = `
        <div class="step-header">
            <button type="button" class="btn-step-toggle" onclick="toggleWorkflowStep(this)" title="折りたたむ / Collapse">▼</button>
            <span class="step-number">Step ${stepNumber}</span>
            <span class="step-summary">
                <span class="step-summary-name">${initialStepName}</span>
                <span class="step-summary-type">${stepTypeLabel}</span>
            </span>
            <div class="step-controls">
                <button type="button" class="btn btn-move btn-sm" onclick="moveWorkflowStepUp(this)" title="上に移動 / Move up">▲</button>
                <button type="button" class="btn btn-move btn-sm" onclick="moveWorkflowStepDown(this)" title="下に移動 / Move down">▼</button>
                <button type="button" class="btn btn-danger btn-sm" onclick="removeWorkflowStep(this)" title="削除 / Remove">✕</button>
            </div>
        </div>
        <div class="step-body">
        <div class="form-group">
            <label>ステップ名 / Step Name:</label>
            <input type="text" class="step-name" value="${stepData ? escapeHtmlGlobal(stepData.step_name) : 'step' + stepNumber}"
                   placeholder="step1, summarize, etc." oninput="validateStepNameInput(this); updateStepSummary(this);">
            <div class="step-name-warning" style="display: none; color: #e74c3c; font-size: 0.8rem; margin-top: 0.25rem;"></div>
        </div>
        <div class="form-group">
            <label>ステップタイプ / Step Type:</label>
            <select class="step-type" onchange="onStepTypeChange(${stepNumber}, this.value); updateStepTypeSummary(this);">
                ${stepTypeOptions}
            </select>
        </div>

        <!-- Prompt step fields -->
        <div class="step-type-fields step-type-prompt" style="display: ${stepType === 'prompt' ? 'block' : 'none'};">
            <div class="form-group">
                <label>プロジェクト / Project:</label>
                <select class="step-project" onchange="onStepProjectChange(${stepNumber}, this.value)">
                    <option value="">-- 選択 / Select --</option>
                    ${projectOptions}
                </select>
            </div>
            <div class="form-group">
                <label>プロンプト / Prompt:</label>
                <div style="display: flex; gap: 0.5rem; align-items: center;">
                    <select class="step-prompt" id="step-prompt-${stepNumber}" style="flex: 1;">
                        <option value="">-- プロジェクトを先に選択 / Select project first --</option>
                    </select>
                    <button type="button" class="btn btn-secondary btn-sm" id="step-prompt-edit-${stepNumber}"
                            onclick="openPromptEditorForStep(${stepNumber})"
                            title="プロンプト編集・新規作成 / Edit/Create Prompt" disabled>
                        📝 編集
                    </button>
                </div>
            </div>
            <div class="form-group">
                <label>入力マッピング / Input Mapping:</label>
                <div class="input-mapping-container" id="input-mapping-container-${stepNumber}">
                    <div class="input-mapping-placeholder">
                        <span style="color: #9e9e9e; font-style: italic;">プロンプトを選択してください / Select a prompt first</span>
                    </div>
                </div>
                <small style="color: #7f8c8d; display: block; margin-top: 0.5rem;">
                    変数: {{input.param}} = 初期入力, {{step1.field}} = 前ステップ出力, {{vars.name}} = 変数<br>
                    数式: sum({{step1.score}}, {{step2.score}}) = 合計
                </small>
            </div>
        </div>

        <!-- SET step fields -->
        <div class="step-type-fields step-type-set" style="display: ${stepType === 'set' ? 'block' : 'none'};">
            <div class="form-group">
                <label>変数設定 / Variable Assignments:</label>
                <div class="set-assignments-container" id="set-assignments-${stepNumber}">
                    ${setAssignmentsHtml}
                </div>
                <button type="button" class="btn btn-secondary btn-sm" onclick="addSetAssignment(${stepNumber})" style="margin-top: 0.5rem;">+ 追加</button>
                <small style="color: #7f8c8d; display: block; margin-top: 0.5rem;">
                    {{step1.result}} や {{input.param}} を参照可能。設定した変数は {{vars.変数名}} で参照
                </small>
            </div>
        </div>

        <!-- IF/ELIF/LOOP condition fields -->
        <div class="step-type-fields step-type-condition" style="display: ${['if', 'elif', 'loop'].includes(stepType) ? 'block' : 'none'};">
            <div class="form-group">
                <label>条件設定 / Condition:</label>
                <div class="condition-builder" style="display: flex; gap: 0.5rem; align-items: center; flex-wrap: wrap;">
                    <div class="input-with-var-btn" style="flex: 1; min-width: 120px; display: flex; gap: 4px;">
                        <input type="text" class="condition-left" placeholder="{{step1.parsed}}"
                               value="${escapeHtmlGlobal(conditionLeft)}" style="flex: 1;">
                        <button type="button" class="btn-var-insert" onclick="showVariablePicker(this)" title="変数を挿入 / Insert Variable">{...}</button>
                    </div>
                    <select class="condition-operator" style="width: auto;">
                        <option value="==" ${conditionOperator === '==' ? 'selected' : ''}>== (等しい)</option>
                        <option value="!=" ${conditionOperator === '!=' ? 'selected' : ''}>!= (等しくない)</option>
                        <option value=">" ${conditionOperator === '>' ? 'selected' : ''}>＞ (より大きい)</option>
                        <option value="<" ${conditionOperator === '<' ? 'selected' : ''}>＜ (より小さい)</option>
                        <option value=">=" ${conditionOperator === '>=' ? 'selected' : ''}>＞= (以上)</option>
                        <option value="<=" ${conditionOperator === '<=' ? 'selected' : ''}>＜= (以下)</option>
                        <option value="contains" ${conditionOperator === 'contains' ? 'selected' : ''}>含む</option>
                        <option value="empty" ${conditionOperator === 'empty' ? 'selected' : ''}>空である</option>
                        <option value="not_empty" ${conditionOperator === 'not_empty' ? 'selected' : ''}>空でない</option>
                    </select>
                    <div class="input-with-var-btn" style="flex: 1; min-width: 120px; display: flex; gap: 4px;">
                        <input type="text" class="condition-right" placeholder="true"
                               value="${escapeHtmlGlobal(conditionRight)}" style="flex: 1;">
                        <button type="button" class="btn-var-insert" onclick="showVariablePicker(this)" title="変数を挿入 / Insert Variable">{...}</button>
                    </div>
                </div>
                <small style="color: #7f8c8d; display: block; margin-top: 0.5rem;">
                    {{vars.counter}}, {{step1.score}}, {{input.param}} などが使用可能
                </small>
            </div>
            <div class="form-group loop-max-iterations" style="display: ${stepType === 'loop' ? 'block' : 'none'};">
                <label>最大繰り返し回数 / Max Iterations:</label>
                <div class="input-with-var-btn" style="display: flex; gap: 4px; width: 180px;">
                    <input type="text" class="max-iterations" placeholder="10" value="${maxIterations}" style="width: 100px;">
                    <button type="button" class="btn-var-insert" onclick="showVariablePicker(this)" title="変数を挿入 / Insert Variable">{...}</button>
                </div>
                <small style="color: #7f8c8d; display: block; margin-top: 0.3rem;">
                    数値または {{vars.max}} 形式で指定可能
                </small>
            </div>
        </div>

        <!-- FOREACH fields -->
        <div class="step-type-fields step-type-foreach" style="display: ${stepType === 'foreach' ? 'block' : 'none'};">
            <div class="form-group">
                <label>ソース / Source:</label>
                <div class="input-with-var-btn" style="display: flex; gap: 4px;">
                    <input type="text" class="foreach-source" placeholder="{{step1.items}} または item1,item2,item3"
                           value="${escapeHtmlGlobal(foreachSource)}" style="flex: 1;">
                    <button type="button" class="btn-var-insert" onclick="showVariablePicker(this)" title="変数を挿入 / Insert Variable">{...}</button>
                </div>
                <small style="color: #7f8c8d; display: block; margin-top: 0.25rem;">
                    JSON配列またはカンマ区切りの値
                </small>
            </div>
            <div class="form-group" style="display: flex; gap: 1rem;">
                <div style="flex: 1;">
                    <label>要素変数名 / Item Variable:</label>
                    <input type="text" class="foreach-item-var" value="${escapeHtmlGlobal(foreachItemVar)}" style="width: 100%;">
                </div>
                <div style="flex: 1;">
                    <label>インデックス変数名 / Index Variable:</label>
                    <input type="text" class="foreach-index-var" value="${escapeHtmlGlobal(foreachIndexVar)}" style="width: 100%;">
                </div>
            </div>
            <small style="color: #7f8c8d; display: block;">
                ループ内で {{vars.item}} と {{vars.i}} として参照可能
            </small>
        </div>

        <!-- No config needed for else, endif, endloop, endforeach, break, continue -->
        <div class="step-type-fields step-type-noconfig" style="display: ${['else', 'endif', 'endloop', 'endforeach', 'break', 'continue'].includes(stepType) ? 'block' : 'none'};">
            <div class="form-group">
                <small style="color: #7f8c8d; font-style: italic;">このステップタイプには追加設定がありません</small>
            </div>
        </div>
        </div><!-- end step-body -->
    `;

    container.appendChild(stepDiv);

    // Load prompts for the selected project (only for prompt type steps)
    if (stepType === 'prompt') {
        if (stepData && stepData.project_id) {
            // Editing existing step: load with selected prompt and input mapping
            await loadPromptsForWorkflowStep(stepNumber, stepData.project_id, stepData.prompt_id, stepData.input_mapping);
        } else if (defaultProjectId) {
            // New step with default project: load prompts (no pre-selected prompt)
            await loadPromptsForWorkflowStep(stepNumber, defaultProjectId, null, null);
        }
    }
}

/**
 * Handle step type change - show/hide relevant fields
 */
function onStepTypeChange(stepNumber, stepType) {
    const stepDiv = document.getElementById(`workflow-step-${stepNumber}`);
    if (!stepDiv) return;

    // Hide all type-specific fields
    stepDiv.querySelectorAll('.step-type-fields').forEach(el => el.style.display = 'none');

    // Show relevant fields based on step type
    if (stepType === 'prompt') {
        stepDiv.querySelector('.step-type-prompt').style.display = 'block';
    } else if (stepType === 'set') {
        stepDiv.querySelector('.step-type-set').style.display = 'block';
    } else if (['if', 'elif', 'loop'].includes(stepType)) {
        stepDiv.querySelector('.step-type-condition').style.display = 'block';
        // Show/hide max iterations field for loop
        const maxIterDiv = stepDiv.querySelector('.loop-max-iterations');
        if (maxIterDiv) maxIterDiv.style.display = stepType === 'loop' ? 'block' : 'none';
    } else if (stepType === 'foreach') {
        stepDiv.querySelector('.step-type-foreach').style.display = 'block';
    } else {
        // else, endif, endloop, endforeach, break, continue
        stepDiv.querySelector('.step-type-noconfig').style.display = 'block';
    }
}

/**
 * Add a SET assignment row
 */
function addSetAssignment(stepNumber) {
    const container = document.getElementById(`set-assignments-${stepNumber}`);
    if (!container) return;

    const row = document.createElement('div');
    row.className = 'set-assignment-row';
    row.innerHTML = `
        <div class="input-with-var-btn" style="display: flex; gap: 4px;">
            <input type="text" class="set-var-name" placeholder="変数名" value="">
            <button type="button" class="btn-var-insert" onclick="showVariablePicker(this)" title="変数を挿入 / Insert Variable">{...}</button>
        </div>
        <span>=</span>
        <div class="input-with-var-btn" style="flex: 1; display: flex; gap: 4px;">
            <input type="text" class="set-var-value" placeholder="値 ({{step.field}} も使用可)" value="" style="flex: 1;">
            <button type="button" class="btn-var-insert" onclick="showVariablePicker(this)" title="変数を挿入 / Insert Variable">{...}</button>
        </div>
        <button type="button" class="btn btn-danger btn-sm" onclick="removeSetAssignment(this)">✕</button>
    `;
    container.appendChild(row);
}

/**
 * Remove a SET assignment row
 */
function removeSetAssignment(button) {
    const row = button.closest('.set-assignment-row');
    if (row) row.remove();
}

/**
 * Build condition_config object based on step type
 */
function buildConditionConfig(stepDiv, stepType) {
    const config = {};

    if (stepType === 'set') {
        // Collect SET assignments
        const assignments = {};
        const rows = stepDiv.querySelectorAll('.set-assignment-row');
        rows.forEach(row => {
            const varName = row.querySelector('.set-var-name')?.value?.trim();
            const varValue = row.querySelector('.set-var-value')?.value?.trim();
            if (varName) {
                assignments[varName] = varValue || '';
            }
        });
        if (Object.keys(assignments).length > 0) {
            config.assignments = assignments;
        }
    } else if (['if', 'elif', 'loop'].includes(stepType)) {
        // Collect condition settings
        const conditionLeft = stepDiv.querySelector('.condition-left')?.value?.trim();
        const conditionOperator = stepDiv.querySelector('.condition-operator')?.value;
        const conditionRight = stepDiv.querySelector('.condition-right')?.value?.trim();

        if (conditionLeft) config.left = conditionLeft;
        if (conditionOperator) config.operator = conditionOperator;
        if (conditionRight) config.right = conditionRight;

        // For loop, include max_iterations
        if (stepType === 'loop') {
            const maxIterations = stepDiv.querySelector('.max-iterations')?.value;
            if (maxIterations) config.max_iterations = parseInt(maxIterations);
        }
    } else if (stepType === 'foreach') {
        // Collect FOREACH settings
        const source = stepDiv.querySelector('.foreach-source')?.value?.trim();
        const itemVar = stepDiv.querySelector('.foreach-item-var')?.value?.trim();
        const indexVar = stepDiv.querySelector('.foreach-index-var')?.value?.trim();

        if (source) config.source = source;
        if (itemVar) config.item_var = itemVar;
        if (indexVar) config.index_var = indexVar;
    }

    return config;
}

/**
 * Handle project change in workflow step - load prompts for the selected project
 */
async function onStepProjectChange(stepNumber, projectId) {
    const promptSelect = document.getElementById(`step-prompt-${stepNumber}`);
    if (!promptSelect) return;

    if (!projectId) {
        promptSelect.innerHTML = '<option value="">-- プロジェクトを先に選択 / Select project first --</option>';
        return;
    }

    await loadPromptsForWorkflowStep(stepNumber, projectId, null);
}

/**
 * Load prompts for a workflow step's project
 * @param {number} stepNumber - The step number
 * @param {number} projectId - The project ID
 * @param {number|null} selectedPromptId - Pre-selected prompt ID (for editing)
 * @param {object|null} existingMapping - Existing input mapping data (for editing)
 */
async function loadPromptsForWorkflowStep(stepNumber, projectId, selectedPromptId, existingMapping = null) {
    const promptSelect = document.getElementById(`step-prompt-${stepNumber}`);
    const editBtn = document.getElementById(`step-prompt-edit-${stepNumber}`);
    if (!promptSelect) return;

    promptSelect.innerHTML = '<option value="">読み込み中... / Loading...</option>';
    if (editBtn) editBtn.disabled = true;

    try {
        // Include deleted prompts for workflow editing (to show existing references)
        const response = await fetch(`/api/projects/${projectId}/prompts?include_deleted=true`);
        if (!response.ok) throw new Error('Failed to load prompts');

        const prompts = await response.json();

        let options = '<option value="">-- プロンプトを選択 / Select prompt --</option>';
        prompts.forEach(p => {
            const selected = selectedPromptId && p.id === selectedPromptId ? 'selected' : '';
            const deletedLabel = p.is_deleted ? '（削除済み）' : '';
            const disabled = p.is_deleted && p.id !== selectedPromptId ? 'disabled' : '';
            const style = p.is_deleted ? 'style="color: #999; font-style: italic;"' : '';
            options += `<option value="${p.id}" ${selected} ${disabled} ${style}>${deletedLabel}${escapeHtmlGlobal(p.name)}</option>`;
        });

        promptSelect.innerHTML = options;

        // Add onchange handler to load parameters when prompt changes
        promptSelect.onchange = async () => {
            // Load input mapping UI when prompt is selected (clear existing mapping for new selection)
            await loadInputMappingForStep(stepNumber, promptSelect.value);
        };

        // Enable edit button once prompts are loaded (allows creating new prompts even if none selected)
        if (editBtn) {
            editBtn.disabled = false;
        }

        // Load input mapping UI if prompt was pre-selected (editing existing workflow)
        if (selectedPromptId) {
            await loadInputMappingForStep(stepNumber, selectedPromptId, existingMapping);
        }
    } catch (error) {
        console.error('Error loading prompts for step:', error);
        promptSelect.innerHTML = '<option value="">エラー / Error</option>';
    }
}

/**
 * Load input mapping UI for a workflow step based on selected prompt's parameters
 * @param {number} stepNumber - The step number
 * @param {string|number} promptId - The selected prompt ID
 * @param {object} existingMapping - Optional existing input mapping data
 */
async function loadInputMappingForStep(stepNumber, promptId, existingMapping = null) {
    const container = document.getElementById(`input-mapping-container-${stepNumber}`);
    if (!container) return;

    let parameters = [];
    let promptParams = new Set(); // Track prompt parameter names

    // Fetch parameters from prompt if selected
    if (promptId) {
        container.innerHTML = '<div style="padding: 0.5rem; color: #7f8c8d;">読み込み中... / Loading...</div>';
        try {
            const response = await fetch(`/api/prompts/${promptId}`);
            if (response.ok) {
                const promptData = await response.json();
                parameters = promptData.parameters || [];
                parameters.forEach(p => promptParams.add(p.name));
            }
        } catch (error) {
            console.error('Error loading prompt parameters:', error);
        }
    }

    // Build Key-Value rows
    let html = '<div class="input-mapping-rows">';

    // Add rows for prompt parameters
    for (const param of parameters) {
        const paramName = param.name;
        const existingValue = existingMapping && existingMapping[paramName] ? existingMapping[paramName] : '';

        html += `
            <div class="input-mapping-row" data-param="${escapeHtmlGlobal(paramName)}" data-type="prompt-param">
                <div class="input-mapping-key">
                    <span class="param-name">${escapeHtmlGlobal(paramName)}</span>
                    <span class="param-type">${escapeHtmlGlobal(param.type)}</span>
                </div>
                <div class="input-mapping-value">
                    <input type="text"
                           class="input-mapping-input"
                           data-param="${escapeHtmlGlobal(paramName)}"
                           value="${escapeHtmlGlobal(existingValue)}"
                           placeholder="{{input.${escapeHtmlGlobal(paramName)}}} or {{step1.field}} or sum(...)"
                    >
                    <button type="button" class="btn-var-picker-small"
                            onclick="openVariablePickerForInputMapping(${stepNumber}, '${escapeHtmlGlobal(paramName)}')"
                            title="変数を挿入 / Insert variable">
                        📥
                    </button>
                </div>
            </div>
        `;
    }

    // Add rows for custom mappings (existing mappings not in prompt parameters)
    if (existingMapping) {
        for (const [key, value] of Object.entries(existingMapping)) {
            if (!promptParams.has(key)) {
                html += createCustomMappingRowHtml(stepNumber, key, value);
            }
        }
    }

    html += '</div>';

    // Add button for custom mapping
    html += `
        <div class="input-mapping-add-custom">
            <button type="button" class="btn-add-custom-mapping" onclick="addCustomMappingRow(${stepNumber}, event)">
                ＋ カスタムパラメータを追加 / Add Custom Parameter
            </button>
        </div>
    `;

    container.innerHTML = html;
}

/**
 * Create HTML for a custom mapping row
 */
function createCustomMappingRowHtml(stepNumber, paramName = '', paramValue = '') {
    const uniqueId = `custom-${Date.now()}-${Math.random().toString(36).substr(2, 9)}`;
    return `
        <div class="input-mapping-row input-mapping-custom" data-param="${escapeHtmlGlobal(paramName)}" data-type="custom" data-custom-id="${uniqueId}">
            <div class="input-mapping-key input-mapping-key-editable">
                <input type="text"
                       class="input-mapping-key-input"
                       value="${escapeHtmlGlobal(paramName)}"
                       placeholder="パラメータ名 / param name"
                       onchange="updateCustomMappingParam(this)"
                >
                <button type="button" class="btn-remove-custom-mapping" onclick="removeCustomMappingRow(this)" title="削除">×</button>
            </div>
            <div class="input-mapping-value">
                <input type="text"
                       class="input-mapping-input"
                       data-param="${escapeHtmlGlobal(paramName)}"
                       value="${escapeHtmlGlobal(paramValue)}"
                       placeholder="{{input.param}} or {{step1.field}} or sum(...)"
                >
                <button type="button" class="btn-var-picker-small"
                        onclick="openVariablePickerForCustomMapping(this, ${stepNumber})"
                        title="変数を挿入 / Insert variable">
                    📥
                </button>
            </div>
        </div>
    `;
}

// Common parameter name suggestions for custom parameters
const CUSTOM_PARAM_SUGGESTIONS = [
    { name: 'CONTEXT', description: 'コンテキスト / Context information' },
    { name: 'INPUT_TEXT', description: '入力テキスト / Input text' },
    { name: 'SUMMARY', description: '要約 / Summary' },
    { name: 'RESULT', description: '結果 / Result' },
    { name: 'DATA', description: 'データ / Data' },
    { name: 'PROMPT', description: 'プロンプト / Prompt text' },
    { name: 'OUTPUT', description: '出力 / Output' },
    { name: 'RESPONSE', description: '応答 / Response' },
    { name: 'QUERY', description: 'クエリ / Query' },
    { name: 'ANALYSIS', description: '分析結果 / Analysis' }
];

/**
 * Add a new custom mapping row to a step with suggestion popup
 */
function addCustomMappingRow(stepNumber, event) {
    const container = document.getElementById(`input-mapping-container-${stepNumber}`);
    if (!container) return;

    const rowsContainer = container.querySelector('.input-mapping-rows');
    if (!rowsContainer) return;

    // Get button position for popup placement
    const button = event ? event.currentTarget : null;

    // Show suggestion popup
    showCustomParamSuggestionPopup(stepNumber, rowsContainer, button);
}

/**
 * Show suggestion popup for custom parameter names
 */
function showCustomParamSuggestionPopup(stepNumber, rowsContainer, anchorButton) {
    // Remove any existing popup
    const existingPopup = document.getElementById('custom-param-suggestion-popup');
    if (existingPopup) existingPopup.remove();

    // Create popup
    const popup = document.createElement('div');
    popup.id = 'custom-param-suggestion-popup';
    popup.className = 'custom-param-suggestion-popup';

    // Generate suggestion buttons
    const suggestionsHtml = CUSTOM_PARAM_SUGGESTIONS.map(s => `
        <button type="button" class="suggestion-item" onclick="selectCustomParamSuggestion(${stepNumber}, '${s.name}', this)" title="${s.description}">
            ${s.name}
        </button>
    `).join('');

    popup.innerHTML = `
        <div class="suggestion-header">
            <span>サジェスト / Suggestions</span>
            <button type="button" class="suggestion-close" onclick="closeCustomParamSuggestionPopup()">×</button>
        </div>
        <div class="suggestion-items">
            ${suggestionsHtml}
        </div>
        <div class="suggestion-footer">
            <button type="button" class="suggestion-custom-btn" onclick="addCustomParamWithoutSuggestion(${stepNumber})">
                カスタム入力 / Custom input
            </button>
        </div>
    `;

    // Position popup near the button
    document.body.appendChild(popup);

    if (anchorButton) {
        const rect = anchorButton.getBoundingClientRect();
        popup.style.position = 'fixed';
        popup.style.left = `${rect.left}px`;
        popup.style.top = `${rect.bottom + 5}px`;

        // Ensure popup doesn't go off screen
        const popupRect = popup.getBoundingClientRect();
        if (popupRect.right > window.innerWidth) {
            popup.style.left = `${window.innerWidth - popupRect.width - 10}px`;
        }
        if (popupRect.bottom > window.innerHeight) {
            popup.style.top = `${rect.top - popupRect.height - 5}px`;
        }
    }

    // Close popup when clicking outside
    setTimeout(() => {
        document.addEventListener('click', closePopupOnOutsideClick);
    }, 100);
}

/**
 * Close popup when clicking outside
 */
function closePopupOnOutsideClick(e) {
    const popup = document.getElementById('custom-param-suggestion-popup');
    if (popup && !popup.contains(e.target) && !e.target.closest('.btn-add-custom-mapping')) {
        closeCustomParamSuggestionPopup();
    }
}

/**
 * Close the custom param suggestion popup
 */
function closeCustomParamSuggestionPopup() {
    const popup = document.getElementById('custom-param-suggestion-popup');
    if (popup) popup.remove();
    document.removeEventListener('click', closePopupOnOutsideClick);
}

/**
 * Select a suggested parameter name and create the row
 */
function selectCustomParamSuggestion(stepNumber, paramName, buttonEl) {
    closeCustomParamSuggestionPopup();

    const container = document.getElementById(`input-mapping-container-${stepNumber}`);
    if (!container) return;

    const rowsContainer = container.querySelector('.input-mapping-rows');
    if (!rowsContainer) return;

    const newRowHtml = createCustomMappingRowHtml(stepNumber, paramName, '');
    rowsContainer.insertAdjacentHTML('beforeend', newRowHtml);

    // Focus the value input since name is already filled
    const newRow = rowsContainer.lastElementChild;
    const valueInput = newRow.querySelector('.input-mapping-input');
    if (valueInput) valueInput.focus();
}

/**
 * Add custom param row without suggestion (for custom input)
 */
function addCustomParamWithoutSuggestion(stepNumber) {
    closeCustomParamSuggestionPopup();

    const container = document.getElementById(`input-mapping-container-${stepNumber}`);
    if (!container) return;

    const rowsContainer = container.querySelector('.input-mapping-rows');
    if (!rowsContainer) return;

    const newRowHtml = createCustomMappingRowHtml(stepNumber, '', '');
    rowsContainer.insertAdjacentHTML('beforeend', newRowHtml);

    // Focus the key input for custom name entry
    const newRow = rowsContainer.lastElementChild;
    const keyInput = newRow.querySelector('.input-mapping-key-input');
    if (keyInput) keyInput.focus();
}

/**
 * Remove a custom mapping row
 */
function removeCustomMappingRow(button) {
    const row = button.closest('.input-mapping-row');
    if (row) row.remove();
}

/**
 * Update the data-param attribute when custom param name changes
 */
function updateCustomMappingParam(keyInput) {
    const row = keyInput.closest('.input-mapping-row');
    if (!row) return;

    const newParamName = keyInput.value.trim();
    row.dataset.param = newParamName;

    const valueInput = row.querySelector('.input-mapping-input');
    if (valueInput) {
        valueInput.dataset.param = newParamName;
    }
}

/**
 * Open variable picker for a custom mapping input
 */
function openVariablePickerForCustomMapping(button, stepNumber) {
    const row = button.closest('.input-mapping-row');
    if (!row) return;

    const input = row.querySelector('.input-mapping-input');
    if (input) {
        const container = document.getElementById(`input-mapping-container-${stepNumber}`);
        const stepDiv = container ? container.closest('.workflow-step') : null;
        let actualStepPosition = stepNumber;
        if (stepDiv) {
            const allSteps = document.querySelectorAll('#workflow-steps-container .workflow-step');
            actualStepPosition = Array.from(allSteps).indexOf(stepDiv) + 1;
        }
        openVariablePicker(input, actualStepPosition);
    }
}

/**
 * Open variable picker for a specific input mapping field
 * @param {number} stepNumber - The step number
 * @param {string} paramName - The parameter name
 */
function openVariablePickerForInputMapping(stepNumber, paramName) {
    const container = document.getElementById(`input-mapping-container-${stepNumber}`);
    if (!container) return;

    const input = container.querySelector(`input[data-param="${paramName}"]`);
    if (input) {
        // Find actual step position in the DOM (accounting for reordering)
        const stepDiv = container.closest('.workflow-step');
        let actualStepPosition = stepNumber;
        if (stepDiv) {
            const allSteps = document.querySelectorAll('#workflow-steps-container .workflow-step');
            actualStepPosition = Array.from(allSteps).indexOf(stepDiv) + 1;
        }
        openVariablePicker(input, actualStepPosition);
    }
}

/**
 * Collect input mapping data from Key-Value UI for a step
 * @param {HTMLElement} stepDiv - The step div element
 * @returns {object|null} Input mapping object or null if empty
 */
function collectInputMappingFromStep(stepDiv) {
    const container = stepDiv.querySelector('.input-mapping-container');
    if (!container) return null;

    const rows = container.querySelectorAll('.input-mapping-row');
    if (rows.length === 0) return null;

    const mapping = {};
    let hasValues = false;

    rows.forEach(row => {
        let paramName;
        const isCustom = row.dataset.type === 'custom';

        if (isCustom) {
            // For custom rows, get param name from key input
            const keyInput = row.querySelector('.input-mapping-key-input');
            paramName = keyInput ? keyInput.value.trim() : '';
        } else {
            // For prompt param rows, use data-param
            paramName = row.dataset.param;
        }

        const valueInput = row.querySelector('.input-mapping-input');
        const value = valueInput ? valueInput.value.trim() : '';

        if (paramName && value) {
            mapping[paramName] = value;
            hasValues = true;
        }
    });

    return hasValues ? mapping : null;
}

/**
 * Toggle workflow step collapse/expand
 */
function toggleWorkflowStep(buttonEl) {
    const stepDiv = buttonEl.closest('.workflow-step');
    if (!stepDiv) return;

    const stepBody = stepDiv.querySelector('.step-body');
    const isCollapsed = stepDiv.classList.contains('collapsed');

    if (isCollapsed) {
        // Expand
        stepDiv.classList.remove('collapsed');
        buttonEl.textContent = '▼';
        buttonEl.title = '折りたたむ / Collapse';
    } else {
        // Collapse
        stepDiv.classList.add('collapsed');
        buttonEl.textContent = '▶';
        buttonEl.title = '展開する / Expand';
    }
}

/**
 * Collapse all workflow steps
 */
function collapseAllWorkflowSteps() {
    const container = document.getElementById('workflow-steps-container');
    if (!container) return;

    container.querySelectorAll('.workflow-step').forEach(stepDiv => {
        stepDiv.classList.add('collapsed');
        const toggleBtn = stepDiv.querySelector('.btn-step-toggle');
        if (toggleBtn) {
            toggleBtn.textContent = '▶';
            toggleBtn.title = '展開する / Expand';
        }
    });
}

/**
 * Expand all workflow steps
 */
function expandAllWorkflowSteps() {
    const container = document.getElementById('workflow-steps-container');
    if (!container) return;

    container.querySelectorAll('.workflow-step').forEach(stepDiv => {
        stepDiv.classList.remove('collapsed');
        const toggleBtn = stepDiv.querySelector('.btn-step-toggle');
        if (toggleBtn) {
            toggleBtn.textContent = '▼';
            toggleBtn.title = '折りたたむ / Collapse';
        }
    });
}

/**
 * Update step summary name when input changes
 */
function updateStepSummary(inputEl) {
    const stepDiv = inputEl.closest('.workflow-step');
    if (!stepDiv) return;

    const summaryName = stepDiv.querySelector('.step-summary-name');
    if (summaryName) {
        summaryName.textContent = inputEl.value || '(unnamed)';
    }
}

/**
 * Update step summary type when type changes
 */
function updateStepTypeSummary(selectEl) {
    const stepDiv = selectEl.closest('.workflow-step');
    if (!stepDiv) return;

    const stepTypeLabels = {
        'prompt': '📝 プロンプト',
        'set': '📦 SET',
        'if': '🔀 IF',
        'elif': '🔀 ELIF',
        'else': '🔀 ELSE',
        'endif': '🔀 ENDIF',
        'loop': '🔄 LOOP',
        'endloop': '🔄 ENDLOOP',
        'foreach': '🔄 FOREACH',
        'endforeach': '🔄 ENDFOREACH',
        'break': '⏹ BREAK',
        'continue': '⏭ CONTINUE'
    };

    const summaryType = stepDiv.querySelector('.step-summary-type');
    if (summaryType) {
        summaryType.textContent = stepTypeLabels[selectEl.value] || selectEl.value;
    }
}

/**
 * Remove a step from the workflow form
 */
function removeWorkflowStep(buttonEl) {
    const stepDiv = buttonEl.closest('.workflow-step');
    if (stepDiv) {
        stepDiv.remove();
        renumberWorkflowSteps();
        // Re-validate all step names after removal
        document.querySelectorAll('.workflow-step .step-name').forEach(input => {
            validateStepNameInput(input);
        });
    }
}

/**
 * Validate step name input in real-time
 * Checks for: format, reserved names, duplicates
 */
function validateStepNameInput(inputEl) {
    const stepDiv = inputEl.closest('.workflow-step');
    const warningEl = stepDiv.querySelector('.step-name-warning');
    if (!warningEl) return;

    const name = inputEl.value.trim();
    let warning = '';

    // Check format
    if (name && !/^[a-zA-Z][a-zA-Z0-9_]*$/.test(name)) {
        warning = '英字で始まり、英数字とアンダースコアのみ使用可 / Must start with letter, alphanumeric and underscore only';
    }

    // Check reserved names
    const reservedNames = ['input'];
    if (name && reservedNames.includes(name.toLowerCase())) {
        warning = '"input" は予約語です / "input" is reserved';
    }

    // Check duplicates
    if (name && !warning) {
        const allNames = [];
        document.querySelectorAll('.workflow-step .step-name').forEach(inp => {
            if (inp !== inputEl) {
                allNames.push(inp.value.trim());
            }
        });
        if (allNames.includes(name)) {
            warning = `同名のステップが存在します / Duplicate step name "${name}"`;
        }
    }

    // Show/hide warning
    if (warning) {
        warningEl.textContent = warning;
        warningEl.style.display = 'block';
        inputEl.style.borderColor = '#e74c3c';
    } else {
        warningEl.textContent = '';
        warningEl.style.display = 'none';
        inputEl.style.borderColor = '';
    }
}

/**
 * Move a workflow step up (swap with previous sibling)
 */
function moveWorkflowStepUp(buttonEl) {
    const stepDiv = buttonEl.closest('.workflow-step');
    if (!stepDiv) return;

    const prevStep = stepDiv.previousElementSibling;
    if (prevStep && prevStep.classList.contains('workflow-step')) {
        stepDiv.parentNode.insertBefore(stepDiv, prevStep);
        renumberWorkflowSteps();
    }
}

/**
 * Move a workflow step down (swap with next sibling)
 */
function moveWorkflowStepDown(buttonEl) {
    const stepDiv = buttonEl.closest('.workflow-step');
    if (!stepDiv) return;

    const nextStep = stepDiv.nextElementSibling;
    if (nextStep && nextStep.classList.contains('workflow-step')) {
        stepDiv.parentNode.insertBefore(nextStep, stepDiv);
        renumberWorkflowSteps();
    }
}

/**
 * Renumber all workflow steps after reordering
 */
function renumberWorkflowSteps() {
    const container = document.getElementById('workflow-steps-container');
    const steps = container.querySelectorAll('.workflow-step');

    steps.forEach((step, index) => {
        const stepNumber = index + 1;
        // Update step number display
        const stepNumberEl = step.querySelector('.step-number');
        if (stepNumberEl) {
            stepNumberEl.textContent = `Step ${stepNumber}`;
        }
    });
}

/**
 * Save workflow (create or update)
 */
async function saveWorkflow() {
    const workflowId = document.getElementById('workflow-id').value;
    const name = document.getElementById('workflow-name').value.trim();
    const description = document.getElementById('workflow-description').value.trim();
    const autoContext = document.getElementById('workflow-auto-context').checked;

    if (!name) {
        alert('ワークフロー名を入力してください / Please enter workflow name');
        return;
    }

    // Collect steps from workflow editor container only
    const container = document.getElementById('workflow-steps-container');
    if (!container) {
        alert('ワークフローエディタが見つかりません / Workflow editor not found');
        return;
    }
    const stepDivs = container.querySelectorAll('.workflow-step');
    const steps = [];
    let stepOrder = 0;

    for (const stepDiv of stepDivs) {
        stepOrder++;
        const stepNameInput = stepDiv.querySelector('input.step-name');
        const stepName = stepNameInput ? stepNameInput.value.trim() : '';
        const stepTypeSelect = stepDiv.querySelector('.step-type');
        const stepType = stepTypeSelect ? stepTypeSelect.value : 'prompt';
        const projectSelect = stepDiv.querySelector('.step-project');
        const projectId = projectSelect ? projectSelect.value : '';
        const promptSelect = stepDiv.querySelector('.step-prompt');
        const promptId = promptSelect ? promptSelect.value : '';

        if (!stepName) {
            alert(`Step ${stepOrder}: ステップ名は必須です / Step name is required`);
            return;
        }

        // For prompt type steps, project is required
        if (stepType === 'prompt' && !projectId) {
            alert(`Step ${stepOrder}: プロンプトステップにはプロジェクトが必須です / Project is required for prompt steps`);
            return;
        }

        // Build condition_config based on step type
        const conditionConfig = buildConditionConfig(stepDiv, stepType);

        const stepData = {
            step_name: stepName,
            step_type: stepType,
            step_order: stepOrder,
            execution_mode: 'sequential'
        };

        // Include project_id and prompt_id only for prompt type steps
        if (stepType === 'prompt') {
            if (projectId) stepData.project_id = parseInt(projectId);
            if (promptId) stepData.prompt_id = parseInt(promptId);

            // Collect input mapping from Key-Value UI
            const inputMapping = collectInputMappingFromStep(stepDiv);
            if (inputMapping && Object.keys(inputMapping).length > 0) {
                stepData.input_mapping = inputMapping;
            }
        }

        // Include condition_config for control flow steps
        if (conditionConfig && Object.keys(conditionConfig).length > 0) {
            stepData.condition_config = conditionConfig;
        }

        steps.push(stepData);
    }

    // Validate step names uniqueness and format
    const stepNames = steps.map(s => s.step_name);
    const duplicates = stepNames.filter((name, index) => stepNames.indexOf(name) !== index);
    if (duplicates.length > 0) {
        alert(`ステップ名が重複しています / Duplicate step names: ${[...new Set(duplicates)].join(', ')}\n\n各ステップ名はユニークである必要があります。`);
        return;
    }

    // Check for reserved names
    const reservedNames = ['input', 'vars'];  // 'input' and 'vars' are reserved
    const usedReserved = stepNames.filter(name => reservedNames.includes(name.toLowerCase()));
    if (usedReserved.length > 0) {
        alert(`予約語のステップ名は使用できません / Reserved step names cannot be used: ${usedReserved.join(', ')}\n\n"input" と "vars" は予約されています。`);
        return;
    }

    // Validate step name format (alphanumeric and underscore only)
    const invalidNames = stepNames.filter(name => !/^[a-zA-Z][a-zA-Z0-9_]*$/.test(name));
    if (invalidNames.length > 0) {
        alert(`ステップ名の形式が不正です / Invalid step name format: ${invalidNames.join(', ')}\n\n英字で始まり、英数字とアンダースコアのみ使用できます。`);
        return;
    }

    try {
        let savedWorkflowId;

        if (workflowId) {
            // Update existing workflow
            const response = await fetch(`/api/workflows/${workflowId}`, {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ name, description, auto_context: autoContext })
            });

            if (!response.ok) throw new Error('Failed to update workflow');

            // Update steps: delete all and re-add
            const existingWorkflow = await response.json();
            for (const step of existingWorkflow.steps) {
                await fetch(`/api/workflows/${workflowId}/steps/${step.id}`, { method: 'DELETE' });
            }
            for (const step of steps) {
                await fetch(`/api/workflows/${workflowId}/steps`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(step)
                });
            }

            savedWorkflowId = workflowId;
        } else {
            // Create new workflow (include project_id)
            const response = await fetch('/api/workflows', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    name,
                    description,
                    project_id: selectedWorkflowProjectId,
                    auto_context: autoContext,
                    steps
                })
            });

            if (!response.ok) throw new Error('Failed to create workflow');

            const savedWorkflow = await response.json();
            savedWorkflowId = savedWorkflow.id;
        }

        // Reload the workflow list
        await loadWorkflows();

        // Refresh single execution dropdown
        await refreshSingleExecutionTargets();

        // Show success message
        showWorkflowSaveSuccess();

        // Re-select the saved workflow to keep it visible
        if (savedWorkflowId) {
            await selectWorkflow(savedWorkflowId);
        }

    } catch (error) {
        console.error('Error saving workflow:', error);
        alert('ワークフローの保存に失敗しました / Failed to save workflow: ' + error.message);
    }
}

/**
 * Show a success message when workflow is saved
 */
function showWorkflowSaveSuccess() {
    // Remove any existing success message
    const existingMsg = document.querySelector('.workflow-save-success');
    if (existingMsg) existingMsg.remove();

    const msg = document.createElement('div');
    msg.className = 'workflow-save-success';
    msg.innerHTML = '✓ ワークフローを保存しました / Workflow saved successfully';
    msg.style.cssText = `
        position: fixed;
        top: 20px;
        right: 20px;
        background: #10b981;
        color: white;
        padding: 12px 24px;
        border-radius: 8px;
        box-shadow: 0 4px 12px rgba(0,0,0,0.15);
        z-index: 10000;
        font-weight: 500;
        animation: slideIn 0.3s ease-out;
    `;

    document.body.appendChild(msg);

    // Auto-remove after 3 seconds
    setTimeout(() => {
        msg.style.animation = 'fadeOut 0.3s ease-out';
        setTimeout(() => msg.remove(), 300);
    }, 3000);
}

/**
 * Select and display a workflow
 */
async function selectWorkflow(workflowId) {
    try {
        const response = await fetch(`/api/workflows/${workflowId}`);
        if (!response.ok) throw new Error('Failed to load workflow');
        selectedWorkflow = await response.json();

        // Update list selection
        document.querySelectorAll('.workflow-item').forEach(el => el.classList.remove('selected'));
        const selectedItem = document.querySelector(`.workflow-item[onclick="selectWorkflow(${workflowId})"]`);
        if (selectedItem) selectedItem.classList.add('selected');

        // Show editor with workflow data
        document.getElementById('workflow-editor-title').textContent = 'ワークフロー編集 / Edit Workflow';
        document.getElementById('workflow-editor-id-info').textContent = `ID: ${selectedWorkflow.id}`;
        document.getElementById('workflow-id').value = selectedWorkflow.id;
        document.getElementById('workflow-name').value = selectedWorkflow.name;
        document.getElementById('workflow-description').value = selectedWorkflow.description || '';
        document.getElementById('workflow-auto-context').checked = selectedWorkflow.auto_context || false;

        // Clear and rebuild steps
        document.getElementById('workflow-steps-container').innerHTML = '';
        workflowStepCounter = 0;

        for (const step of selectedWorkflow.steps) {
            await addWorkflowStep(step);
        }

        document.getElementById('workflow-editor').style.display = 'block';

        // Show Save As, Export, and Delete buttons for existing workflow
        document.getElementById('btn-workflow-save-as').style.display = 'inline-block';
        document.getElementById('btn-workflow-export').style.display = 'inline-block';
        document.getElementById('btn-workflow-delete').style.display = 'inline-block';

    } catch (error) {
        console.error('Error selecting workflow:', error);
        alert('ワークフローの読み込みに失敗しました / Failed to load workflow');
    }
}

/**
 * Save workflow with a new name (Clone)
 */
async function saveWorkflowAs() {
    if (!selectedWorkflow) {
        alert('ワークフローを選択してください / Please select a workflow');
        return;
    }

    const newName = prompt(
        `新しいワークフロー名を入力してください\nEnter new workflow name:`,
        selectedWorkflow.name + ' (Copy)'
    );

    if (!newName || newName.trim() === '') {
        return;
    }

    try {
        const response = await fetch(`/api/workflows/${selectedWorkflow.id}/clone`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ new_name: newName.trim() })
        });

        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.detail || 'Failed to clone workflow');
        }

        const newWorkflow = await response.json();
        await loadWorkflows();
        await refreshSingleExecutionTargets();
        await selectWorkflow(newWorkflow.id);

    } catch (error) {
        console.error('Error cloning workflow:', error);
        alert('ワークフローの複製に失敗しました / Failed to clone workflow: ' + error.message);
    }
}

/**
 * Delete selected workflow
 */
async function deleteWorkflow() {
    if (!selectedWorkflow) {
        alert('ワークフローを選択してください / Please select a workflow');
        return;
    }

    if (!confirm(`"${selectedWorkflow.name}" を削除しますか？\nDelete "${selectedWorkflow.name}"?`)) {
        return;
    }

    try {
        const response = await fetch(`/api/workflows/${selectedWorkflow.id}`, { method: 'DELETE' });
        if (!response.ok) throw new Error('Failed to delete workflow');

        selectedWorkflow = null;
        hideWorkflowEditor();
        await loadWorkflows();
        await refreshSingleExecutionTargets();

    } catch (error) {
        console.error('Error deleting workflow:', error);
        alert('ワークフローの削除に失敗しました / Failed to delete workflow');
    }
}

/**
 * Export workflow as JSON file
 */
async function exportWorkflow() {
    if (!selectedWorkflow) {
        alert('ワークフローを選択してください / Please select a workflow');
        return;
    }

    try {
        const response = await fetch(`/api/workflows/${selectedWorkflow.id}/export`);
        if (!response.ok) throw new Error('Failed to export workflow');

        const exportData = await response.json();

        // Create downloadable JSON file
        const jsonStr = JSON.stringify(exportData, null, 2);
        const blob = new Blob([jsonStr], { type: 'application/json' });
        const url = URL.createObjectURL(blob);

        // Create temp link and trigger download
        const a = document.createElement('a');
        a.href = url;
        a.download = `workflow_${selectedWorkflow.name.replace(/[^a-zA-Z0-9_-]/g, '_')}.json`;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(url);

    } catch (error) {
        console.error('Error exporting workflow:', error);
        alert('ワークフローのエクスポートに失敗しました / Failed to export workflow');
    }
}

/**
 * Show import workflow dialog
 */
function showImportWorkflowDialog() {
    // Create file input
    const input = document.createElement('input');
    input.type = 'file';
    input.accept = '.json';

    input.onchange = async (e) => {
        const file = e.target.files[0];
        if (!file) return;

        try {
            const text = await file.text();
            const workflowData = JSON.parse(text);

            // Validate basic structure
            if (!workflowData.name || !Array.isArray(workflowData.steps)) {
                throw new Error('Invalid workflow JSON format');
            }

            // Ask for optional new name
            const newName = prompt(
                `インポートするワークフロー名\nWorkflow name to import:`,
                workflowData.name
            );

            if (newName === null) return; // Cancelled

            // Import workflow
            const response = await fetch('/api/workflows/import', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    workflow_json: workflowData,
                    new_name: newName || workflowData.name
                })
            });

            if (!response.ok) {
                const error = await response.json();
                throw new Error(error.detail || 'Import failed');
            }

            const imported = await response.json();
            alert(`ワークフロー "${imported.name}" をインポートしました\nWorkflow "${imported.name}" imported successfully`);

            // Reload and select
            await loadWorkflows();
            await refreshSingleExecutionTargets();
            await selectWorkflow(imported.id);

        } catch (error) {
            console.error('Error importing workflow:', error);
            alert(`インポートに失敗しました: ${error.message}\nImport failed: ${error.message}`);
        }
    };

    input.click();
}

// ========== Variable Picker for Workflow Steps ==========

let variablePickerTarget = null;  // The textarea that will receive the inserted variable
let cachedWorkflowVariables = null;  // Cached variables data
let variablePickerCurrentStep = null;  // Current step number for variable filtering

/**
 * Open the variable picker dialog
 * @param {HTMLElement} targetTextarea - The textarea to insert the variable into
 * @param {number} stepNumber - Optional step number for filtering (workflow context)
 */
async function openVariablePicker(targetTextarea, stepNumber = null) {
    variablePickerTarget = targetTextarea;
    variablePickerCurrentStep = stepNumber;

    // Show the modal
    document.getElementById('variable-picker-overlay').classList.add('active');

    // Clear search
    document.getElementById('variable-search').value = '';

    // Load variables with context-aware filtering
    await loadWorkflowVariablesWithContext(stepNumber);
}

/**
 * Close the variable picker dialog
 */
function closeVariablePicker() {
    document.getElementById('variable-picker-overlay').classList.remove('active');
    variablePickerTarget = null;
    // Reset to variables tab when closing
    switchVariablePickerTab('variables');
    // Clear composition area when closing
    const compositionInput = document.getElementById('vp-composition-input');
    if (compositionInput) {
        compositionInput.value = '';
    }
}

/**
 * Switch between variable picker tabs (variables / formula)
 * @param {string} tabName - The tab to switch to ('variables' or 'formula')
 */
function switchVariablePickerTab(tabName) {
    // Update tab buttons
    document.querySelectorAll('.vp-tab').forEach(tab => {
        tab.classList.toggle('active', tab.dataset.tab === tabName);
    });

    // Update tab contents
    document.querySelectorAll('.vp-tab-content').forEach(content => {
        const contentId = content.id;
        const isActive = contentId === `vp-tab-${tabName}`;
        content.classList.toggle('active', isActive);
        content.style.display = isActive ? 'flex' : 'none';
    });

    // Focus on the appropriate input
    if (tabName === 'variables') {
        const searchInput = document.getElementById('variable-search');
        if (searchInput) searchInput.focus();
    } else if (tabName === 'formula') {
        const formulaInput = document.getElementById('formula-input');
        if (formulaInput) formulaInput.focus();
    }
}

/**
 * Insert the formula value into the target input
 */
function insertFormulaValue() {
    const formulaInput = document.getElementById('formula-input');
    if (!formulaInput) return;

    const formula = formulaInput.value.trim();
    if (!formula) {
        alert('数式を入力してください / Please enter a formula');
        return;
    }

    if (!variablePickerTarget) {
        console.error('No target textarea for formula insertion');
        closeVariablePicker();
        return;
    }

    const textarea = variablePickerTarget;
    const start = textarea.selectionStart;
    const end = textarea.selectionEnd;
    const text = textarea.value;

    // Insert formula at cursor position
    textarea.value = text.substring(0, start) + formula + text.substring(end);

    // Move cursor after inserted formula
    const newPos = start + formula.length;
    textarea.selectionStart = newPos;
    textarea.selectionEnd = newPos;

    // Focus back on textarea
    textarea.focus();

    // Clear formula input
    formulaInput.value = '';

    // Close the picker
    closeVariablePicker();

    // Trigger input event for any listeners
    textarea.dispatchEvent(new Event('input', { bubbles: true }));
}

/**
 * Clear the formula input
 */
function clearFormulaInput() {
    const formulaInput = document.getElementById('formula-input');
    if (formulaInput) {
        formulaInput.value = '';
        formulaInput.focus();
    }
}

/**
 * Set a formula example in the input (legacy - now uses composition area)
 * @param {string} example - The example formula to set
 */
function setFormulaExample(example) {
    appendToComposition(example);
}

/**
 * Append text to the composition area textarea
 * @param {string} text - The text to append
 */
function appendToComposition(text) {
    const compositionInput = document.getElementById('vp-composition-input');
    if (!compositionInput) {
        console.error('Composition input not found');
        return;
    }

    const currentValue = compositionInput.value;
    const start = compositionInput.selectionStart;
    const end = compositionInput.selectionEnd;

    // Insert at cursor position (or append if no selection)
    if (document.activeElement === compositionInput && start !== end) {
        // Replace selection
        compositionInput.value = currentValue.substring(0, start) + text + currentValue.substring(end);
        compositionInput.selectionStart = compositionInput.selectionEnd = start + text.length;
    } else if (document.activeElement === compositionInput) {
        // Insert at cursor
        compositionInput.value = currentValue.substring(0, start) + text + currentValue.substring(start);
        compositionInput.selectionStart = compositionInput.selectionEnd = start + text.length;
    } else {
        // Append to end
        compositionInput.value = currentValue + text;
    }

    // Focus the composition input
    compositionInput.focus();

    // Flash effect to show something was added
    compositionInput.style.backgroundColor = '#dbeafe';
    setTimeout(() => {
        compositionInput.style.backgroundColor = '';
    }, 200);
}

/**
 * Insert the composition area value into the target input
 */
function insertCompositionValue() {
    const compositionInput = document.getElementById('vp-composition-input');
    if (!compositionInput) return;

    const value = compositionInput.value.trim();
    if (!value) {
        alert('作成エリアにテキストを入力してください / Please enter text in the composition area');
        return;
    }

    if (!variablePickerTarget) {
        console.error('No target textarea for composition insertion');
        closeVariablePicker();
        return;
    }

    const textarea = variablePickerTarget;
    const start = textarea.selectionStart;
    const end = textarea.selectionEnd;
    const text = textarea.value;

    // Insert value at cursor position
    textarea.value = text.substring(0, start) + value + text.substring(end);

    // Move cursor after inserted value
    const newPos = start + value.length;
    textarea.selectionStart = newPos;
    textarea.selectionEnd = newPos;

    // Focus back on textarea
    textarea.focus();

    // Clear composition area
    compositionInput.value = '';

    // Close the picker
    closeVariablePicker();

    // Trigger input event for any listeners
    textarea.dispatchEvent(new Event('input', { bubbles: true }));
}

/**
 * Clear the composition area
 */
function clearComposition() {
    const compositionInput = document.getElementById('vp-composition-input');
    if (compositionInput) {
        compositionInput.value = '';
        compositionInput.focus();
    }
}

/**
 * Load workflow variables from API and render them (legacy function)
 */
async function loadWorkflowVariables() {
    await loadWorkflowVariablesWithContext(null);
}

/**
 * Load workflow variables with context-aware filtering for workflow steps
 * @param {number} stepNumber - Current step number (for filtering previous steps)
 */
async function loadWorkflowVariablesWithContext(stepNumber) {
    const container = document.getElementById('variable-categories');

    try {
        // Fetch variables if not cached
        if (!cachedWorkflowVariables) {
            const response = await fetch('/api/workflow-variables');
            if (!response.ok) throw new Error('Failed to load variables');
            cachedWorkflowVariables = await response.json();
        }

        // Get current workflow steps for context-aware filtering
        const workflowSteps = getCurrentWorkflowSteps();

        // Build dynamic categories based on workflow context
        const filteredCategories = buildFilteredCategories(stepNumber, workflowSteps);

        renderVariableCategories(filteredCategories, '');
    } catch (error) {
        console.error('Error loading workflow variables:', error);
        container.innerHTML = `<p style="padding: 1rem; color: #e74c3c;">変数の読み込みに失敗しました / Failed to load variables</p>`;
    }
}

/**
 * Get current workflow steps from the editor form
 * @returns {Array} Array of step info objects {stepName, projectId, promptId, promptName}
 */
function getCurrentWorkflowSteps() {
    const steps = [];
    // Scope to workflow editor container to avoid picking up job result display elements
    const container = document.getElementById('workflow-steps-container');
    if (!container) {
        return steps;
    }
    const stepDivs = container.querySelectorAll('.workflow-step');

    stepDivs.forEach((stepDiv, index) => {
        const stepNumber = index + 1;
        const stepNameInput = stepDiv.querySelector('input.step-name');
        const projectSelect = stepDiv.querySelector('.step-project');
        const promptSelect = stepDiv.querySelector('.step-prompt');

        // Safely get step name - input elements have .value, spans don't
        let stepName = `step${stepNumber}`;
        if (stepNameInput && typeof stepNameInput.value === 'string') {
            stepName = stepNameInput.value.trim() || stepName;
        }

        steps.push({
            stepNumber: stepNumber,
            stepName: stepName,
            projectId: projectSelect ? parseInt(projectSelect.value) || null : null,
            promptId: promptSelect ? parseInt(promptSelect.value) || null : null,
            promptName: promptSelect && promptSelect.selectedIndex >= 0
                ? promptSelect.options[promptSelect.selectedIndex].text
                : ''
        });
    });

    return steps;
}

/**
 * Build filtered variable categories based on workflow context
 * Only shows variables from prompts actually used in the workflow
 * @param {number} currentStepNumber - The step number being edited
 * @param {Array} workflowSteps - Array of all workflow steps
 * @returns {Array} Filtered categories for the variable picker
 */
function buildFilteredCategories(currentStepNumber, workflowSteps) {
    const categories = [];

    // Get the set of promptIds actually used in this workflow
    const usedPromptIds = new Set();
    for (const step of workflowSteps) {
        if (step.promptId) {
            usedPromptIds.add(step.promptId);
        }
    }

    // Category 1: Initial Input - only show params from prompts used in the workflow
    const inputVars = [];
    const addedInputVars = new Set(); // Track duplicates

    // Only add a generic hint if workflow has steps
    if (workflowSteps.length > 0) {
        inputVars.push({
            name: "(入力パラメータ名)",
            variable: "{{input.パラメータ名}}",
            type: "input",
            source: "ワークフロー初期入力"
        });
    }

    // Add input params ONLY from prompts used in the workflow steps
    if (cachedWorkflowVariables && usedPromptIds.size > 0) {
        for (const cat of cachedWorkflowVariables.categories) {
            if (cat.category_id.startsWith('prompt_') && cat.category_id.endsWith('_input')) {
                // Extract prompt ID from category_id (format: "prompt_123_input")
                const match = cat.category_id.match(/^prompt_(\d+)_input$/);
                if (match) {
                    const promptId = parseInt(match[1]);
                    // Only include if this prompt is used in the workflow
                    if (usedPromptIds.has(promptId)) {
                        for (const v of cat.variables) {
                            // Avoid duplicate variable names
                            if (!addedInputVars.has(v.variable)) {
                                addedInputVars.add(v.variable);
                                inputVars.push({
                                    name: v.name,
                                    variable: v.variable,
                                    type: "input",
                                    source: v.source
                                });
                            }
                        }
                    }
                }
            }
        }
    }

    // Only add input category if there are variables
    if (inputVars.length > 0) {
        categories.push({
            category_id: "input",
            category_name: "📥 初期入力 / Initial Input",
            variables: inputVars
        });
    }

    // Category 2+: Previous steps' outputs (for steps before currentStepNumber)
    if (currentStepNumber && workflowSteps.length > 0) {
        for (const step of workflowSteps) {
            // Only show steps before the current one
            if (step.stepNumber >= currentStepNumber) continue;
            if (!step.promptId) continue;

            const stepVars = [];

            // Get output fields from cached variables for this prompt
            if (cachedWorkflowVariables) {
                for (const cat of cachedWorkflowVariables.categories) {
                    if (cat.category_id === `prompt_${step.promptId}`) {
                        for (const v of cat.variables) {
                            // Replace placeholder step name with actual step name
                            const actualVar = v.variable.replace('ステップ名', step.stepName);
                            stepVars.push({
                                name: v.name,
                                variable: actualVar,
                                type: "output",
                                source: `${step.promptName || v.source}`
                            });
                        }
                    }
                }
            }

            // Add raw_response for this step
            stepVars.push({
                name: "raw (生出力)",
                variable: `{{${step.stepName}.raw}}`,
                type: "output",
                source: "生のLLM出力"
            });

            // Add role-specific variables (SYSTEM, USER, ASSISTANT, CONTEXT)
            stepVars.push({
                name: "SYSTEM",
                variable: `{{${step.stepName}.SYSTEM}}`,
                type: "role",
                source: "システムメッセージ"
            });
            stepVars.push({
                name: "USER",
                variable: `{{${step.stepName}.USER}}`,
                type: "role",
                source: "ユーザーメッセージ"
            });
            stepVars.push({
                name: "ASSISTANT",
                variable: `{{${step.stepName}.ASSISTANT}}`,
                type: "role",
                source: "アシスタント応答"
            });
            stepVars.push({
                name: "CONTEXT (会話履歴)",
                variable: `{{${step.stepName}.CONTEXT}}`,
                type: "context",
                source: "それまでの全会話履歴"
            });

            if (stepVars.length > 0) {
                categories.push({
                    category_id: `step_${step.stepNumber}`,
                    category_name: `📤 Step ${step.stepNumber}: ${step.stepName} の出力`,
                    variables: stepVars
                });
            }
        }
    }

    // When no workflow context (stepNumber is null), show outputs from all steps in workflow
    // This is used when variable picker is opened without a specific step context
    if (!currentStepNumber && workflowSteps.length > 0) {
        for (const step of workflowSteps) {
            if (!step.promptId) continue;

            const stepVars = [];

            if (cachedWorkflowVariables) {
                for (const cat of cachedWorkflowVariables.categories) {
                    if (cat.category_id === `prompt_${step.promptId}`) {
                        for (const v of cat.variables) {
                            const actualVar = v.variable.replace('ステップ名', step.stepName);
                            stepVars.push({
                                name: v.name,
                                variable: actualVar,
                                type: "output",
                                source: `${step.promptName || v.source}`
                            });
                        }
                    }
                }
            }

            stepVars.push({
                name: "raw (生出力)",
                variable: `{{${step.stepName}.raw}}`,
                type: "output",
                source: "生のLLM出力"
            });

            // Add role-specific variables
            stepVars.push({
                name: "SYSTEM",
                variable: `{{${step.stepName}.SYSTEM}}`,
                type: "role",
                source: "システムメッセージ"
            });
            stepVars.push({
                name: "USER",
                variable: `{{${step.stepName}.USER}}`,
                type: "role",
                source: "ユーザーメッセージ"
            });
            stepVars.push({
                name: "ASSISTANT",
                variable: `{{${step.stepName}.ASSISTANT}}`,
                type: "role",
                source: "アシスタント応答"
            });
            stepVars.push({
                name: "CONTEXT (会話履歴)",
                variable: `{{${step.stepName}.CONTEXT}}`,
                type: "context",
                source: "それまでの全会話履歴"
            });

            if (stepVars.length > 0) {
                categories.push({
                    category_id: `step_${step.stepNumber}`,
                    category_name: `📤 Step ${step.stepNumber}: ${step.stepName} の出力`,
                    variables: stepVars
                });
            }
        }
    }

    return categories;
}

/**
 * Get the selected project ID for the workflow context
 * @returns {number|null} The selected project ID or null
 */
function getWorkflowSelectedProjectId() {
    const projectSelect = document.getElementById('workflow-project-select');
    return projectSelect ? parseInt(projectSelect.value) || null : null;
}

/**
 * Render variable categories with optional filtering
 * @param {Array} categories - Array of category objects
 * @param {string} searchQuery - Search query to filter by
 */
function renderVariableCategories(categories, searchQuery) {
    const container = document.getElementById('variable-categories');
    const query = searchQuery.toLowerCase().trim();

    let html = '';
    let hasResults = false;

    for (const category of categories) {
        // Filter variables by search query
        const filteredVars = category.variables.filter(v =>
            !query ||
            v.name.toLowerCase().includes(query) ||
            v.variable.toLowerCase().includes(query) ||
            v.source.toLowerCase().includes(query)
        );

        if (filteredVars.length === 0) continue;
        hasResults = true;

        html += `
            <div class="variable-category" data-category="${escapeHtmlGlobal(category.category_id)}">
                <div class="variable-category-header" onclick="toggleVariableCategory(this)">
                    <span class="toggle-icon">▼</span>
                    <span>${escapeHtmlGlobal(category.category_name)}</span>
                    <span style="margin-left: auto; font-size: 0.75rem; color: #9e9e9e;">(${filteredVars.length})</span>
                </div>
                <ul class="variable-list">
        `;

        for (const varInfo of filteredVars) {
            html += `
                <li class="variable-item" onclick="insertVariable('${escapeHtmlGlobal(varInfo.variable)}')">
                    <span class="var-name">${escapeHtmlGlobal(varInfo.name)}</span>
                    <span class="var-syntax">${escapeHtmlGlobal(varInfo.variable)}</span>
                    <span class="var-source">${escapeHtmlGlobal(varInfo.source)}</span>
                </li>
            `;
        }

        html += `
                </ul>
            </div>
        `;
    }

    if (!hasResults) {
        html = `<div class="variable-no-results">検索結果がありません / No results found</div>`;
    }

    container.innerHTML = html;
}

/**
 * Toggle category collapsed state
 * @param {HTMLElement} headerElement - The clicked header element
 */
function toggleVariableCategory(headerElement) {
    const categoryDiv = headerElement.closest('.variable-category');
    categoryDiv.classList.toggle('collapsed');
}

/**
 * Filter variables based on search query
 * Uses the same context-aware filtering as initial load
 * @param {string} query - Search query
 */
function filterVariables(query) {
    if (cachedWorkflowVariables) {
        // Re-build filtered categories with current workflow context
        const workflowSteps = getCurrentWorkflowSteps();
        const filteredCategories = buildFilteredCategories(variablePickerCurrentStep, workflowSteps);
        renderVariableCategories(filteredCategories, query);
    }
}

/**
 * Insert a variable at the cursor position in the target textarea
 * @param {string} variable - The variable syntax to insert (e.g., "{{step1.answer}}")
 */
function insertVariable(variable) {
    // Now appends to composition area instead of direct insertion
    appendToComposition(variable);
}

/**
 * Refresh cached workflow variables (call when prompts/parsers change)
 */
function refreshWorkflowVariables() {
    cachedWorkflowVariables = null;
}

/**
 * Open variable picker for a specific workflow step's input mapping textarea
 * @param {number} stepNumber - The step number
 */
function openVariablePickerForStep(stepNumber) {
    const textarea = document.getElementById(`step-input-mapping-${stepNumber}`);
    if (textarea) {
        // Find actual step position in the DOM (accounting for reordering)
        const stepDiv = textarea.closest('.workflow-step');
        let actualStepPosition = stepNumber;
        if (stepDiv) {
            const allSteps = document.querySelectorAll('.workflow-step');
            actualStepPosition = Array.from(allSteps).indexOf(stepDiv) + 1;
        }
        openVariablePicker(textarea, actualStepPosition);
    } else {
        console.error(`Textarea for step ${stepNumber} not found`);
    }
}

// Close variable picker when clicking overlay background
document.addEventListener('DOMContentLoaded', () => {
    const overlay = document.getElementById('variable-picker-overlay');
    if (overlay) {
        overlay.addEventListener('click', (e) => {
            if (e.target === overlay) {
                closeVariablePicker();
            }
        });
    }

    // Initialize draggable window
    initDraggableWindow('prompt-editor-window', 'prompt-editor-header');
});


// ========== Draggable Prompt Editor Window ==========

let promptEditorDragState = {
    isDragging: false,
    startX: 0,
    startY: 0,
    startLeft: 0,
    startTop: 0
};

/**
 * Initialize draggable functionality for a window
 * @param {string} windowId - The window element ID
 * @param {string} headerId - The header element ID (drag handle)
 */
function initDraggableWindow(windowId, headerId) {
    const windowEl = document.getElementById(windowId);
    const headerEl = document.getElementById(headerId);

    if (!windowEl || !headerEl) return;

    headerEl.addEventListener('mousedown', (e) => {
        if (e.target.tagName === 'BUTTON') return;

        promptEditorDragState.isDragging = true;
        promptEditorDragState.startX = e.clientX;
        promptEditorDragState.startY = e.clientY;

        const rect = windowEl.getBoundingClientRect();
        promptEditorDragState.startLeft = rect.left;
        promptEditorDragState.startTop = rect.top;

        // Remove transform for absolute positioning during drag
        windowEl.style.transform = 'none';
        windowEl.style.left = rect.left + 'px';
        windowEl.style.top = rect.top + 'px';

        e.preventDefault();
    });

    document.addEventListener('mousemove', (e) => {
        if (!promptEditorDragState.isDragging) return;

        const deltaX = e.clientX - promptEditorDragState.startX;
        const deltaY = e.clientY - promptEditorDragState.startY;

        let newLeft = promptEditorDragState.startLeft + deltaX;
        let newTop = promptEditorDragState.startTop + deltaY;

        // Keep window within viewport bounds
        newLeft = Math.max(0, Math.min(newLeft, window.innerWidth - 100));
        newTop = Math.max(0, Math.min(newTop, window.innerHeight - 50));

        windowEl.style.left = newLeft + 'px';
        windowEl.style.top = newTop + 'px';
    });

    document.addEventListener('mouseup', () => {
        promptEditorDragState.isDragging = false;
    });
}

/**
 * Open the unified prompt editor window
 * This function is used by single execution, batch execution, and workflow editing
 * @param {number} projectId - The project ID
 * @param {number|null} promptId - The prompt ID to select (optional)
 * @param {number|null} stepNumber - Workflow step number (null for single/batch execution)
 */
async function openPromptEditorWindow(projectId, promptId = null, stepNumber = null) {
    if (!projectId) {
        alert('プロジェクトを選択してください / Please select a project');
        return;
    }

    // Show window
    const windowEl = document.getElementById('prompt-editor-window');
    windowEl.style.display = 'flex';
    windowEl.classList.remove('minimized');

    // Reset to prompt tab
    switchPromptEditorTab('prompt');

    // Set step and project info
    document.getElementById('prompt-editor-step-number').value = stepNumber || '';
    document.getElementById('prompt-editor-project-id').value = projectId;
    document.getElementById('prompt-editor-status').textContent = '読み込み中...';

    // Load all prompts for the project
    try {
        const includeDeleted = stepNumber ? '?include_deleted=true' : '';
        const targetsResponse = await fetch(`/api/projects/${projectId}/execution-targets${includeDeleted}`);
        if (!targetsResponse.ok) throw new Error('Failed to load prompts');
        const targets = await targetsResponse.json();
        const prompts = targets.prompts || [];

        // Populate prompt selector
        const editorPromptSelector = document.getElementById('prompt-editor-prompt-selector');
        editorPromptSelector.innerHTML = prompts.map(p => {
            const deletedLabel = p.is_deleted ? '（削除済み）' : '';
            const disabled = p.is_deleted && p.id !== promptId ? 'disabled' : '';
            return `<option value="${p.id}" ${promptId && p.id === promptId ? 'selected' : ''} ${disabled}>${deletedLabel}${p.name}</option>`;
        }).join('');

        // If no prompt was selected, select the first active one
        const activePrompts = prompts.filter(p => !p.is_deleted);
        const selectedPromptId = promptId || (activePrompts.length > 0 ? activePrompts[0].id : null);

        if (selectedPromptId) {
            editorPromptSelector.value = selectedPromptId;
            await loadPromptIntoEditor(selectedPromptId);
        } else {
            // No prompts available
            document.getElementById('prompt-editor-prompt-id').value = '';
            document.getElementById('prompt-editor-name').value = '';
            document.getElementById('prompt-editor-description').value = '';
            document.getElementById('prompt-editor-template').value = '';
            document.getElementById('prompt-editor-id-info').textContent = '';
            document.getElementById('prompt-editor-revision-info').textContent = '';
            document.getElementById('prompt-editor-status').textContent = 'プロンプトがありません。新規作成してください。';
            loadParserConfigToUI({ type: 'none' });
            renderPromptRevisions([]);
            renderPromptEditorTags([]);
        }
    } catch (error) {
        console.error('Error loading prompts:', error);
        document.getElementById('prompt-editor-status').textContent = 'エラー: プロンプトの読み込みに失敗しました';
    }
}

/**
 * Open prompt editor for a workflow step
 * @param {number} stepNumber - The step number in the workflow form
 */
async function openPromptEditorForStep(stepNumber) {
    const stepDiv = document.getElementById(`workflow-step-${stepNumber}`);
    if (!stepDiv) {
        alert('ステップが見つかりません / Step not found');
        return;
    }

    // Get project ID from step's project selector
    const projectSelect = stepDiv.querySelector('.step-project');
    if (!projectSelect || !projectSelect.value) {
        alert('プロジェクトを先に選択してください / Please select a project first');
        return;
    }
    const projectId = parseInt(projectSelect.value);

    const promptSelect = document.getElementById(`step-prompt-${stepNumber}`);
    const promptId = promptSelect && promptSelect.value ? parseInt(promptSelect.value) : null;

    // Use the unified prompt editor window
    await openPromptEditorWindow(projectId, promptId, stepNumber);
}

/**
 * Load a specific prompt into the editor
 * @param {number} promptId - The prompt ID to load
 */
async function loadPromptIntoEditor(promptId) {
    document.getElementById('prompt-editor-prompt-id').value = promptId;
    document.getElementById('prompt-editor-status').textContent = '読み込み中...';

    // Clear revisions list immediately to prevent duplicates
    const revisionsListEl = document.getElementById('prompt-editor-revisions');
    if (revisionsListEl) {
        revisionsListEl.innerHTML = '<li style="padding: 0.5rem; color: #9e9e9e; font-size: 0.8rem;">読み込み中...</li>';
    }
    document.getElementById('prompt-editor-current-revision').value = '';
    document.getElementById('prompt-editor-revision-info').textContent = '';
    document.getElementById('prompt-editor-id-info').textContent = `ID: ${promptId}`;

    // Clear tags display immediately
    const tagsContainer = document.getElementById('prompt-editor-current-tags');
    if (tagsContainer) {
        tagsContainer.innerHTML = '';
    }

    try {
        const [promptResponse, revisionsResponse, tagsResponse] = await Promise.all([
            fetch(`/api/prompts/${promptId}`),
            fetch(`/api/prompts/${promptId}/revisions`),
            fetch(`/api/prompts/${promptId}/tags`)
        ]);

        if (!promptResponse.ok) throw new Error('Failed to load prompt');

        const prompt = await promptResponse.json();
        document.getElementById('prompt-editor-template').value = prompt.prompt_template || '';
        document.getElementById('prompt-editor-name').value = prompt.name || '';
        document.getElementById('prompt-editor-description').value = prompt.description || '';
        document.getElementById('prompt-editor-status').textContent = '';

        // Load parser config to UI
        loadParserConfigToUI(prompt.parser_config);

        // Render revisions
        if (revisionsResponse.ok) {
            const revisions = await revisionsResponse.json();
            renderPromptRevisions(revisions);
            // Mark latest revision as current or show "New" for prompts with no revisions
            if (revisions.length > 0) {
                document.getElementById('prompt-editor-current-revision').value = revisions[0].revision;
                document.getElementById('prompt-editor-revision-info').textContent = `(Rev. ${revisions[0].revision})`;
            } else {
                document.getElementById('prompt-editor-current-revision').value = '';
                document.getElementById('prompt-editor-revision-info').textContent = '(新規 / New)';
            }
        }

        // Render prompt tags
        if (tagsResponse.ok) {
            const tagsData = await tagsResponse.json();
            // API returns List[TagResponse] directly, not {tags: [...]}
            renderPromptEditorTags(Array.isArray(tagsData) ? tagsData : []);
        } else {
            renderPromptEditorTags([]);
        }
    } catch (error) {
        console.error('Error loading prompt:', error);
        document.getElementById('prompt-editor-template').value = '';
        document.getElementById('prompt-editor-status').textContent = 'エラー: プロンプトの読み込みに失敗しました';
        loadParserConfigToUI({ type: 'none' });
        renderPromptRevisions([]);
        renderPromptEditorTags([]);
    }
}

/**
 * Handle prompt change in the editor's prompt selector
 * @param {string} promptIdStr - The selected prompt ID as string
 */
async function onPromptEditorPromptChange(promptIdStr) {
    if (!promptIdStr) return;
    const promptId = parseInt(promptIdStr);
    await loadPromptIntoEditor(promptId);

    // Also update the step's prompt selector
    const stepNumber = document.getElementById('prompt-editor-step-number').value;
    if (stepNumber) {
        const stepPromptSelect = document.getElementById(`step-prompt-${stepNumber}`);
        if (stepPromptSelect) {
            stepPromptSelect.value = promptId;
            // Trigger input mapping update
            const stepDiv = document.getElementById(`workflow-step-${stepNumber}`);
            if (stepDiv) {
                const projectSelect = stepDiv.querySelector('.step-project');
                if (projectSelect && projectSelect.value) {
                    await loadPromptsForWorkflowStep(parseInt(stepNumber), parseInt(projectSelect.value), promptId, null);
                }
            }
        }
    }
}

/**
 * Delete prompt from the editor
 * Soft deletes the prompt and updates the UI
 */
async function deletePromptFromEditor() {
    const promptId = document.getElementById('prompt-editor-prompt-id').value;
    const projectId = document.getElementById('prompt-editor-project-id').value;
    const promptName = document.getElementById('prompt-editor-name').value;

    if (!promptId) {
        alert('削除するプロンプトが選択されていません / No prompt selected to delete');
        return;
    }

    try {
        // Check if prompt is used in any workflows
        const usageResponse = await fetch(`/api/prompts/${promptId}/usage`);
        let confirmMessage = `プロンプト「${promptName}」を削除しますか？\nDelete prompt "${promptName}"?`;

        if (usageResponse.ok) {
            const usage = await usageResponse.json();
            if (usage.is_used) {
                const workflowDetails = usage.workflows.map(wf => {
                    const steps = wf.step_names.join(', ');
                    return `  • ${wf.name} (ステップ: ${steps})`;
                }).join('\n');

                confirmMessage = `プロンプト「${promptName}」を削除しますか？\n\n` +
                    `📋 使用中のワークフロー (${usage.workflow_count}件):\n` +
                    `${workflowDetails}\n\n` +
                    `※ 削除後もワークフローは動作しますが、プロンプトは「（削除済み）」と表示されます。`;
            }
        }

        if (!confirm(confirmMessage)) {
            return;
        }

        const statusEl = document.getElementById('prompt-editor-status');
        statusEl.textContent = '削除中...';

        const response = await fetch(`/api/prompts/${promptId}`, {
            method: 'DELETE'
        });

        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.detail?.message || error.detail || 'Failed to delete prompt');
        }

        statusEl.textContent = 'プロンプトを削除しました / Prompt deleted';
        statusEl.style.color = '#27ae60';

        const deletedPromptId = parseInt(promptId);

        // Update the step's prompt selector FIRST if in workflow context
        // Pass the deleted promptId so it shows as "(削除済み)" in the selector
        const stepNumber = document.getElementById('prompt-editor-step-number').value;
        if (stepNumber && projectId) {
            await loadPromptsForWorkflowStep(parseInt(stepNumber), parseInt(projectId), deletedPromptId, null);
        }

        // Reload prompts in the editor dropdown (include deleted to show the deleted prompt)
        const promptsResponse = await fetch(`/api/projects/${projectId}/prompts?include_deleted=true`);
        if (promptsResponse.ok) {
            const prompts = await promptsResponse.json();
            const selector = document.getElementById('prompt-editor-prompt-selector');

            if (prompts.length > 0) {
                // Rebuild selector with deleted prompt still selected and labeled
                selector.innerHTML = prompts.map(p => {
                    const isDeleted = p.is_deleted;
                    const isSelected = p.id === deletedPromptId;
                    const deletedLabel = isDeleted ? '（削除済み）' : '';
                    const disabled = isDeleted && !isSelected ? 'disabled' : '';
                    const style = isDeleted ? 'style="color: #999; font-style: italic;"' : '';
                    return `<option value="${p.id}" ${isSelected ? 'selected' : ''} ${disabled} ${style}>${deletedLabel}${escapeHtmlGlobal(p.name)}</option>`;
                }).join('');

                // Update the name field to show (削除済み)
                const nameField = document.getElementById('prompt-editor-name');
                if (nameField && !nameField.value.includes('（削除済み）')) {
                    nameField.value = '（削除済み）' + nameField.value;
                }
            } else {
                // No prompts left - clear the editor
                selector.innerHTML = '<option value="">-- プロンプトなし --</option>';
                document.getElementById('prompt-editor-prompt-id').value = '';
                document.getElementById('prompt-editor-name').value = '';
                document.getElementById('prompt-editor-description').value = '';
                document.getElementById('prompt-editor-template').value = '';
                document.getElementById('prompt-editor-id-info').textContent = '';
                document.getElementById('prompt-editor-revision-info').textContent = '';
                document.getElementById('prompt-editor-revisions').innerHTML = '';
                loadParserConfigToUI({ type: 'none' });
            }
        }

        // Update main UI execution targets
        if (currentProjectId) {
            await loadExecutionTargets(currentProjectId);
        }

        setTimeout(() => {
            statusEl.textContent = '';
            statusEl.style.color = '';
        }, 3000);

    } catch (error) {
        console.error('Error deleting prompt:', error);
        const statusEl = document.getElementById('prompt-editor-status');
        statusEl.textContent = `エラー: ${error.message}`;
        statusEl.style.color = '#e74c3c';
    }
}

/**
 * Show create prompt form in the editor
 */
async function showCreatePromptInEditor() {
    const projectId = document.getElementById('prompt-editor-project-id').value;
    if (!projectId) {
        alert('プロジェクトIDが見つかりません / Project ID not found');
        return;
    }

    const name = prompt('新しいプロンプトの名前を入力してください / Enter new prompt name:', '新規プロンプト');
    if (!name || !name.trim()) return;

    const statusEl = document.getElementById('prompt-editor-status');
    statusEl.textContent = '作成中...';

    try {
        const response = await fetch(`/api/projects/${projectId}/prompts`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                name: name.trim(),
                description: '',
                prompt_template: 'プロンプトを入力してください / Enter your prompt here'
            })
        });

        if (!response.ok) throw new Error('Failed to create prompt');

        const newPrompt = await response.json();
        statusEl.textContent = `✓ プロンプト「${name}」を作成しました`;
        statusEl.style.color = '#27ae60';

        // Refresh prompt selector and select the new prompt
        const targetsResponse = await fetch(`/api/projects/${projectId}/execution-targets?include_deleted=true`);
        if (targetsResponse.ok) {
            const targets = await targetsResponse.json();
            const prompts = targets.prompts || [];

            const editorPromptSelector = document.getElementById('prompt-editor-prompt-selector');
            editorPromptSelector.innerHTML = prompts.map(p => {
                const deletedLabel = p.is_deleted ? '（削除済み）' : '';
                const disabled = p.is_deleted ? 'disabled' : '';
                return `<option value="${p.id}" ${p.id === newPrompt.id ? 'selected' : ''} ${disabled}>${deletedLabel}${p.name}</option>`;
            }).join('');

            // Load the new prompt
            await loadPromptIntoEditor(newPrompt.id);

            // Update the step's prompt selector
            const stepNumber = document.getElementById('prompt-editor-step-number').value;
            if (stepNumber) {
                await loadPromptsForWorkflowStep(parseInt(stepNumber), parseInt(projectId), newPrompt.id, null);
            }
        }

        setTimeout(() => {
            statusEl.textContent = '';
            statusEl.style.color = '#7f8c8d';
        }, 3000);
    } catch (error) {
        console.error('Error creating prompt:', error);
        statusEl.textContent = 'エラー: プロンプトの作成に失敗しました';
        statusEl.style.color = '#e74c3c';
    }
}

/**
 * Close the prompt editor window
 */
function closePromptEditor() {
    const windowEl = document.getElementById('prompt-editor-window');
    windowEl.style.display = 'none';
}

/**
 * Minimize/restore the prompt editor window
 */
function minimizePromptEditor() {
    const windowEl = document.getElementById('prompt-editor-window');
    windowEl.classList.toggle('minimized');
}

/**
 * Save the prompt template from the editor
 */
async function savePromptFromEditor() {
    const promptId = document.getElementById('prompt-editor-prompt-id').value;
    const template = document.getElementById('prompt-editor-template').value;
    const promptName = document.getElementById('prompt-editor-name').value.trim();
    const promptDescription = document.getElementById('prompt-editor-description').value.trim();
    const statusEl = document.getElementById('prompt-editor-status');

    if (!promptId) {
        statusEl.textContent = 'エラー: プロンプトIDがありません';
        return;
    }

    if (!promptName) {
        statusEl.textContent = 'エラー: プロンプト名は必須です';
        statusEl.style.color = '#e74c3c';
        return;
    }

    // Validate role markers
    const markerValidation = validateRoleMarkers(template);

    // Show errors and block save
    if (!markerValidation.valid) {
        statusEl.innerHTML = '<span style="color: #e74c3c;">❌ ' + markerValidation.errors.join('<br>') + '</span>';
        statusEl.style.color = '#e74c3c';
        return;
    }

    // Show warnings but allow save
    if (markerValidation.warnings.length > 0) {
        const proceed = confirm('⚠️ 警告:\n\n' + markerValidation.warnings.join('\n') + '\n\nこのまま保存しますか？');
        if (!proceed) {
            statusEl.textContent = '保存をキャンセルしました';
            statusEl.style.color = '#7f8c8d';
            return;
        }
    }

    statusEl.textContent = '保存中...';

    try {
        // Save metadata (name, description) first
        const metadataPayload = {
            name: promptName,
            description: promptDescription
        };

        const metadataResponse = await fetch(`/api/prompts/${promptId}`, {
            method: 'PUT',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify(metadataPayload)
        });

        if (!metadataResponse.ok) throw new Error('Failed to save prompt metadata');

        // Build save payload with both prompt_template and parser_config
        // parser_config must be a JSON string, not an object
        const savePayload = {
            prompt_template: template,
            parser_config: JSON.stringify(getCurrentParserConfig())
        };

        const response = await fetch(`/api/prompts/${promptId}/revisions/latest`, {
            method: 'PUT',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify(savePayload)
        });

        if (!response.ok) throw new Error('Failed to save prompt');

        const result = await response.json();

        if (result.is_new) {
            statusEl.textContent = `✓ 新しいリビジョン ${result.revision} として保存しました`;
            statusEl.style.color = '#27ae60';
            // Update current revision
            document.getElementById('prompt-editor-current-revision').value = result.revision;
            document.getElementById('prompt-editor-revision-info').textContent = `(Rev. ${result.revision})`;
            // Refresh revision list
            await loadPromptRevisions();
        } else {
            statusEl.textContent = '✓ 保存しました（テンプレート変更なし）';
            statusEl.style.color = '#27ae60';
        }

        // Refresh prompt list to show updated name
        await refreshPromptList();

        // Refresh workflow variables cache since prompt changed
        refreshWorkflowVariables();

        // Refresh input mapping for the current workflow step if parameters changed
        const stepNumber = document.getElementById('prompt-editor-step-number').value;
        if (stepNumber && result.is_new) {
            // Parameters may have changed, refresh input mapping
            await refreshWorkflowStepInputMapping(parseInt(stepNumber), promptId);
        }

        setTimeout(() => {
            statusEl.textContent = '';
            statusEl.style.color = '#7f8c8d';
        }, 3000);
    } catch (error) {
        console.error('Error saving prompt:', error);
        statusEl.textContent = 'エラー: 保存に失敗しました';
        statusEl.style.color = '#e74c3c';
    }
}

/**
 * Refresh prompt list in the dropdown after saving
 */
async function refreshPromptList() {
    const projectSelect = document.getElementById('projectSelect');
    if (!projectSelect || !projectSelect.value) return;

    const projectId = parseInt(projectSelect.value);
    try {
        const response = await fetch(`/api/projects/${projectId}/execution-targets`);
        if (!response.ok) return;

        const data = await response.json();
        const promptSelect = document.getElementById('promptSelect');
        const currentPromptId = promptSelect.value;

        // Update prompt select options
        promptSelect.innerHTML = '<option value="">-- プロンプトを選択 --</option>';
        if (data.prompts) {
            data.prompts.forEach(p => {
                const opt = document.createElement('option');
                opt.value = p.id;
                opt.textContent = p.name;
                promptSelect.appendChild(opt);
            });
        }

        // Restore selection
        if (currentPromptId) {
            promptSelect.value = currentPromptId;
        }
    } catch (error) {
        console.error('Error refreshing prompt list:', error);
    }

    // Also refresh workflow step prompt dropdowns
    await refreshWorkflowStepPromptDropdowns();
}

/**
 * Refresh all workflow step prompt dropdowns to show updated prompt names
 */
async function refreshWorkflowStepPromptDropdowns() {
    const container = document.getElementById('workflow-steps-container');
    if (!container) return;

    const stepDivs = container.querySelectorAll('.workflow-step');
    if (stepDivs.length === 0) return;

    // Collect all unique project IDs and their steps
    const projectSteps = new Map(); // projectId -> [{stepNumber, promptSelect, selectedPromptId}]

    stepDivs.forEach((stepDiv, index) => {
        const stepNumber = index + 1;
        const projectSelect = stepDiv.querySelector('.step-project');
        const promptSelect = stepDiv.querySelector('.step-prompt');

        if (projectSelect && promptSelect && projectSelect.value) {
            const projectId = projectSelect.value;
            const selectedPromptId = promptSelect.value;

            if (!projectSteps.has(projectId)) {
                projectSteps.set(projectId, []);
            }
            projectSteps.get(projectId).push({
                stepNumber,
                promptSelect,
                selectedPromptId
            });
        }
    });

    // Fetch prompts for each project and update dropdowns
    for (const [projectId, steps] of projectSteps) {
        try {
            const response = await fetch(`/api/projects/${projectId}/prompts?include_deleted=true`);
            if (!response.ok) continue;

            const prompts = await response.json();

            // Update each step's prompt dropdown
            for (const step of steps) {
                let options = '<option value="">-- プロンプトを選択 / Select prompt --</option>';
                prompts.forEach(p => {
                    const selected = step.selectedPromptId && p.id == step.selectedPromptId ? 'selected' : '';
                    const deletedLabel = p.is_deleted ? '（削除済み）' : '';
                    const disabled = p.is_deleted && p.id != step.selectedPromptId ? 'disabled' : '';
                    const style = p.is_deleted ? 'style="color: #999; font-style: italic;"' : '';
                    options += `<option value="${p.id}" ${selected} ${disabled} ${style}>${deletedLabel}${escapeHtmlGlobal(p.name)}</option>`;
                });
                step.promptSelect.innerHTML = options;
            }
        } catch (error) {
            console.error(`Error refreshing prompts for project ${projectId}:`, error);
        }
    }
}

/**
 * Refresh input mapping for a specific workflow step when prompt parameters change
 * @param {number} stepNumber - The step number to refresh
 * @param {number} promptId - The prompt ID to load parameters from
 */
async function refreshWorkflowStepInputMapping(stepNumber, promptId) {
    const container = document.getElementById(`input-mapping-container-${stepNumber}`);
    if (!container || !promptId) return;

    try {
        // Get current input mapping values before refresh
        const existingMapping = {};
        const rows = container.querySelectorAll('.input-mapping-row');
        rows.forEach(row => {
            const param = row.dataset.param;
            const input = row.querySelector('.input-mapping-input');
            if (param && input && input.value) {
                existingMapping[param] = input.value;
            }
        });

        // Also preserve custom mappings
        const customMappings = {};
        const customRows = container.querySelectorAll('.input-mapping-custom');
        customRows.forEach(row => {
            const keyInput = row.querySelector('.input-mapping-key-input');
            const valueInput = row.querySelector('.input-mapping-input');
            if (keyInput && keyInput.value && valueInput) {
                customMappings[keyInput.value] = valueInput.value;
            }
        });

        // Reload input mapping with preserved values
        await loadInputMappingForStep(stepNumber, promptId, { ...existingMapping, ...customMappings });

        console.log(`[refreshWorkflowStepInputMapping] Refreshed input mapping for step ${stepNumber}, prompt ${promptId}`);
    } catch (error) {
        console.error(`Error refreshing input mapping for step ${stepNumber}:`, error);
    }
}

// ========== Prompt Editor Tab Functions ==========

/**
 * Switch between prompt and parser tabs
 * @param {string} tabId - 'prompt' or 'parser'
 */
function switchPromptEditorTab(tabId) {
    // Update tab buttons
    document.querySelectorAll('.prompt-tab-btn').forEach(btn => {
        btn.classList.toggle('active', btn.dataset.tab === tabId);
    });

    // Update tab content
    document.querySelectorAll('.prompt-editor-tab-content').forEach(content => {
        const isActive = content.id === `prompt-editor-tab-${tabId}`;
        content.classList.toggle('active', isActive);
        content.style.display = isActive ? 'flex' : 'none';
    });
}

/**
 * Get current parser configuration from the UI (simple JSON textarea)
 * @returns {Object} Parser configuration object
 */
function getCurrentParserConfig() {
    const parserType = document.getElementById('prompt-editor-parser-type').value;
    const configText = document.getElementById('prompt-editor-parser-config').value.trim();

    if (parserType === 'none' || !configText) {
        return { type: 'none' };
    }

    try {
        const config = JSON.parse(configText);
        config.type = parserType;  // Ensure type matches select
        return config;
    } catch (e) {
        // Invalid JSON, return with just type
        return { type: parserType };
    }
}

/**
 * Handle parser type change - update the config textarea
 */
function onPromptEditorParserTypeChange() {
    const parserType = document.getElementById('prompt-editor-parser-type').value;
    const textarea = document.getElementById('prompt-editor-parser-config');

    // Try to parse current config
    let currentConfig = { type: parserType };
    try {
        const existing = JSON.parse(textarea.value);
        currentConfig = { ...existing, type: parserType };
    } catch (e) {
        // Create default config for type
        if (parserType === 'json_path') {
            currentConfig = { type: 'json_path', paths: {} };
        } else if (parserType === 'regex') {
            currentConfig = { type: 'regex', patterns: {} };
        } else if (parserType === 'csv_template') {
            currentConfig = { type: 'csv_template', columns: [] };
        } else {
            currentConfig = { type: 'none' };
        }
    }

    textarea.value = JSON.stringify(currentConfig, null, 2);
}

/**
 * Load parser config from API response and populate UI (simple JSON textarea)
 * @param {Object|string} parserConfig - Parser configuration
 */
function loadParserConfigToUI(parserConfig) {
    let config = parserConfig;

    // Parse if it's a string
    if (typeof config === 'string') {
        try {
            config = JSON.parse(config);
        } catch (e) {
            config = { type: 'none' };
        }
    }

    if (!config || typeof config !== 'object') {
        config = { type: 'none' };
    }

    const parserType = config.type || 'none';
    document.getElementById('prompt-editor-parser-type').value = parserType;
    document.getElementById('prompt-editor-parser-config').value = JSON.stringify(config, null, 2);
}

// ========== Prompt Revision Functions ==========

/**
 * Load and display prompt revisions
 */
async function loadPromptRevisions() {
    const promptId = document.getElementById('prompt-editor-prompt-id').value;
    if (!promptId) return;

    const listEl = document.getElementById('prompt-editor-revisions');
    listEl.innerHTML = '<li style="padding: 0.5rem; color: #9e9e9e; font-size: 0.8rem;">読み込み中...</li>';

    try {
        const response = await fetch(`/api/prompts/${promptId}/revisions`);
        if (!response.ok) throw new Error('Failed to load revisions');

        const revisions = await response.json();
        renderPromptRevisions(revisions);
    } catch (error) {
        console.error('Error loading revisions:', error);
        listEl.innerHTML = '<li style="padding: 0.5rem; color: #e74c3c; font-size: 0.8rem;">エラー</li>';
    }
}

/**
 * Render prompt revisions list
 * @param {Array} revisions - Array of revision objects
 */
function renderPromptRevisions(revisions) {
    const listEl = document.getElementById('prompt-editor-revisions');
    const currentRevision = parseInt(document.getElementById('prompt-editor-current-revision').value) || 0;

    if (!revisions || revisions.length === 0) {
        listEl.innerHTML = '<li style="padding: 0.5rem; color: #9e9e9e; font-size: 0.8rem;">リビジョンなし</li>';
        return;
    }

    let html = '';
    for (const rev of revisions) {
        const isActive = rev.revision === currentRevision;
        const isLatest = revisions[0].revision === rev.revision;
        const dateStr = formatRevisionDate(rev.created_at);

        html += `
            <li class="revision-item ${isActive ? 'active' : ''}" onclick="selectRevision(${rev.revision})" data-revision="${rev.revision}">
                <span class="rev-number">Rev. ${rev.revision}</span>
                ${isLatest ? '<span style="font-size: 0.65rem; background: #4caf50; color: white; padding: 1px 4px; border-radius: 2px; margin-left: 4px;">最新</span>' : ''}
                <span class="rev-date">${dateStr}</span>
                ${!isLatest ? `<div class="rev-actions"><button class="btn-restore" onclick="event.stopPropagation(); restoreRevision(${rev.revision})">復元</button></div>` : ''}
            </li>
        `;
    }

    listEl.innerHTML = html;
}

/**
 * Format revision date for display
 * @param {string} isoDate - ISO date string
 * @returns {string} Formatted date string
 */
function formatRevisionDate(isoDate) {
    if (!isoDate) return '';
    try {
        const date = new Date(isoDate);
        return date.toLocaleString('ja-JP', {
            month: '2-digit',
            day: '2-digit',
            hour: '2-digit',
            minute: '2-digit'
        });
    } catch (e) {
        return isoDate.substring(0, 16).replace('T', ' ');
    }
}

/**
 * Select and load a specific revision
 * @param {number} revisionNumber - The revision number to load
 */
async function selectRevision(revisionNumber) {
    const promptId = document.getElementById('prompt-editor-prompt-id').value;
    if (!promptId) return;

    const statusEl = document.getElementById('prompt-editor-status');
    statusEl.textContent = '読み込み中...';

    try {
        const response = await fetch(`/api/prompts/${promptId}/revisions`);
        if (!response.ok) throw new Error('Failed to load revisions');

        const revisions = await response.json();
        const revision = revisions.find(r => r.revision === revisionNumber);

        if (revision) {
            document.getElementById('prompt-editor-template').value = revision.prompt_template || '';
            document.getElementById('prompt-editor-current-revision').value = revisionNumber;
            document.getElementById('prompt-editor-revision-info').textContent = `(Rev. ${revisionNumber})`;

            // Load parser config for this revision
            loadParserConfigToUI(revision.parser_config);

            // Update active state in list
            document.querySelectorAll('.revision-item').forEach(el => {
                el.classList.remove('active');
                if (parseInt(el.dataset.revision) === revisionNumber) {
                    el.classList.add('active');
                }
            });

            statusEl.textContent = `Rev. ${revisionNumber} を読み込みました`;
            statusEl.style.color = '#2196f3';
            setTimeout(() => {
                statusEl.textContent = '';
                statusEl.style.color = '#7f8c8d';
            }, 2000);
        }
    } catch (error) {
        console.error('Error loading revision:', error);
        statusEl.textContent = 'エラー: リビジョンの読み込みに失敗しました';
        statusEl.style.color = '#e74c3c';
    }
}

/**
 * Restore a past revision (creates a new revision with the old content)
 * @param {number} revisionNumber - The revision number to restore
 */
async function restoreRevision(revisionNumber) {
    const promptId = document.getElementById('prompt-editor-prompt-id').value;
    if (!promptId) return;

    if (!confirm(`リビジョン ${revisionNumber} を復元しますか？\n（新しいリビジョンとして保存されます）`)) {
        return;
    }

    const statusEl = document.getElementById('prompt-editor-status');
    statusEl.textContent = '復元中...';

    try {
        const response = await fetch(`/api/prompts/${promptId}/revisions/${revisionNumber}/restore`, {
            method: 'POST'
        });

        if (!response.ok) throw new Error('Failed to restore revision');

        const result = await response.json();

        statusEl.textContent = `✓ Rev. ${revisionNumber} を Rev. ${result.revision} として復元しました`;
        statusEl.style.color = '#27ae60';

        // Update editor with restored content
        document.getElementById('prompt-editor-template').value = result.prompt_template || '';
        document.getElementById('prompt-editor-current-revision').value = result.revision;
        document.getElementById('prompt-editor-revision-info').textContent = `(Rev. ${result.revision})`;

        // Load parser config for restored revision
        loadParserConfigToUI(result.parser_config);

        // Refresh revision list
        await loadPromptRevisions();

        // Refresh workflow variables
        refreshWorkflowVariables();

        setTimeout(() => {
            statusEl.textContent = '';
            statusEl.style.color = '#7f8c8d';
        }, 3000);
    } catch (error) {
        console.error('Error restoring revision:', error);
        statusEl.textContent = 'エラー: 復元に失敗しました';
        statusEl.style.color = '#e74c3c';
    }
}

// ========== Role Marker Functions ==========

/**
 * Insert a role marker at the cursor position in the prompt template editor
 * @param {string} role - 'SYSTEM', 'USER', or 'ASSISTANT'
 */
function insertRoleMarker(role) {
    const textarea = document.getElementById('prompt-editor-template');
    if (!textarea) return;

    const marker = `[${role}]\n`;
    const start = textarea.selectionStart;
    const end = textarea.selectionEnd;
    const text = textarea.value;

    // Insert marker with newline
    textarea.value = text.substring(0, start) + marker + text.substring(end);

    // Move cursor after the marker
    const newPos = start + marker.length;
    textarea.setSelectionRange(newPos, newPos);
    textarea.focus();
}

/**
 * Validate role markers in the prompt template
 * @param {string} template - The prompt template text
 * @returns {Object} - { valid: boolean, errors: string[], warnings: string[] }
 */
function validateRoleMarkers(template) {
    const errors = [];
    const warnings = [];

    if (!template) {
        return { valid: true, errors, warnings };
    }

    // Count markers
    const systemMatches = template.match(/\[SYSTEM\]/gi) || [];
    const userMatches = template.match(/\[USER\]/gi) || [];
    const assistantMatches = template.match(/\[ASSISTANT\]/gi) || [];

    // Check for duplicate [SYSTEM] markers (error)
    if (systemMatches.length > 1) {
        errors.push(`[SYSTEM] マーカーが ${systemMatches.length} 個あります。[SYSTEM] は1つだけにしてください。`);
    }

    // Check if SYSTEM is not at the beginning (warning)
    if (systemMatches.length > 0) {
        const firstSystemPos = template.search(/\[SYSTEM\]/i);
        const textBefore = template.substring(0, firstSystemPos).trim();
        if (textBefore.length > 0 && !textBefore.match(/^\[USER\]/i)) {
            warnings.push('[SYSTEM] マーカーの前にテキストがあります。[SYSTEM] は通常、最初に配置します。');
        }
    }

    // Check for consecutive same markers (warning)
    const markerPattern = /\[(SYSTEM|USER|ASSISTANT)\]/gi;
    let match;
    let lastRole = null;
    while ((match = markerPattern.exec(template)) !== null) {
        const currentRole = match[1].toUpperCase();
        if (lastRole && lastRole === currentRole) {
            warnings.push(`[${currentRole}] マーカーが連続しています。間に他のロールを挿入することを検討してください。`);
            break; // Only warn once
        }
        lastRole = currentRole;
    }

    return {
        valid: errors.length === 0,
        errors,
        warnings
    };
}

/**
 * Show help modal for role markers (redirects to unified prompt template help)
 */
function showRoleMarkerHelp() {
    // Show the unified prompt template help which includes role markers section
    showPromptTemplateHelp();

    // Scroll to role markers section after a brief delay
    setTimeout(() => {
        const roleMarkersSection = document.getElementById('role-markers');
        if (roleMarkersSection) {
            roleMarkersSection.scrollIntoView({ behavior: 'smooth', block: 'start' });
        }
    }, 100);
}


// ========================================
// Tag Management Functions (v3.1)
// ========================================

let allTags = [];

/**
 * Load tags and model tag configurations for the settings page
 */
async function loadTagsManagement() {
    try {
        // Load all tags
        const tagsResponse = await fetch('/api/tags');
        allTags = await tagsResponse.json();

        renderTagsList();
        await renderModelTagsConfig();
    } catch (error) {
        console.error('Failed to load tags:', error);
        document.getElementById('tags-list').innerHTML = '<p class="error">タグの読み込みに失敗しました</p>';
    }
}

/**
 * Render the tags list in settings
 */
function renderTagsList() {
    const container = document.getElementById('tags-list');
    if (!container) return;

    if (allTags.length === 0) {
        container.innerHTML = '<p style="color: #64748b;">タグがありません</p>';
        return;
    }

    container.innerHTML = allTags.map(tag => {
        const isSystem = tag.is_system;
        const textColor = getContrastColor(tag.color);

        return `
            <div class="tag-item ${isSystem ? 'system-tag' : ''}" style="background-color: ${tag.color}; color: ${textColor};">
                <span class="tag-name">${escapeHtmlGlobal(tag.name)}</span>
                ${isSystem ? '<span class="tag-badge">(システム)</span>' : ''}
                <span class="tag-count">(${tag.prompt_count})</span>
                <div class="tag-actions">
                    <button class="btn-tag-action" onclick="showEditTagModal(${tag.id})" title="編集">✏️</button>
                    ${!isSystem ? `<button class="btn-tag-action" onclick="deleteTag(${tag.id})" title="削除">🗑️</button>` : ''}
                </div>
            </div>
        `;
    }).join('');
}

/**
 * Get contrast color (black or white) based on background color
 */
function getContrastColor(hexColor) {
    const hex = hexColor.replace('#', '');
    const r = parseInt(hex.substr(0, 2), 16);
    const g = parseInt(hex.substr(2, 2), 16);
    const b = parseInt(hex.substr(4, 2), 16);
    const luminance = (0.299 * r + 0.587 * g + 0.114 * b) / 255;
    return luminance > 0.5 ? '#1e293b' : '#ffffff';
}

/**
 * Show create tag modal
 */
function showCreateTagModal() {
    const modalHtml = `
        <div style="padding: 1.5rem;">
            <h3 style="margin-top: 0; margin-bottom: 1rem;">新規タグ作成</h3>
            <form id="create-tag-form" onsubmit="event.preventDefault(); createTag();">
                <div class="tag-form-group">
                    <label>タグ名</label>
                    <input type="text" id="tag-name-input" required placeholder="RedTeam, Production, Test, etc.">
                </div>
                <div class="tag-form-group">
                    <label>カラー</label>
                    <div class="tag-color-picker">
                        <input type="color" id="tag-color-input" value="#6366f1" onchange="updateTagColorPreview()">
                        <div id="tag-color-preview" class="tag-color-preview" style="background-color: #6366f1; color: white;">
                            プレビュー
                        </div>
                    </div>
                </div>
                <div class="tag-form-group">
                    <label>説明 (任意)</label>
                    <input type="text" id="tag-description-input" placeholder="タグの説明">
                </div>
                <div style="display: flex; gap: 0.5rem; margin-top: 1rem;">
                    <button type="submit" class="btn btn-primary">作成</button>
                    <button type="button" class="btn btn-secondary" onclick="closeModal()">キャンセル</button>
                </div>
            </form>
        </div>
    `;

    showModal(modalHtml);
}

/**
 * Update tag color preview
 */
function updateTagColorPreview() {
    const color = document.getElementById('tag-color-input').value;
    const preview = document.getElementById('tag-color-preview');
    const textColor = getContrastColor(color);
    preview.style.backgroundColor = color;
    preview.style.color = textColor;
}

/**
 * Create a new tag
 */
async function createTag() {
    const name = document.getElementById('tag-name-input').value.trim();
    const color = document.getElementById('tag-color-input').value;
    const description = document.getElementById('tag-description-input').value.trim();

    if (!name) {
        alert('タグ名を入力してください');
        return;
    }

    try {
        const response = await fetch('/api/tags', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ name, color, description: description || null })
        });

        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.detail || 'Failed to create tag');
        }

        closeModal();
        await loadTagsManagement();
        alert(`タグ "${name}" を作成しました`);
    } catch (error) {
        alert(`エラー: ${error.message}`);
    }
}

/**
 * Show edit tag modal
 */
function showEditTagModal(tagId) {
    const tag = allTags.find(t => t.id === tagId);
    if (!tag) return;

    const textColor = getContrastColor(tag.color);

    const modalHtml = `
        <div style="padding: 1.5rem;">
            <h3 style="margin-top: 0; margin-bottom: 1rem;">タグ編集</h3>
            <form id="edit-tag-form" onsubmit="event.preventDefault(); updateTag(${tagId});">
                <div class="tag-form-group">
                    <label>タグ名</label>
                    <input type="text" id="edit-tag-name-input" value="${escapeHtmlGlobal(tag.name)}"
                           ${tag.is_system ? 'readonly style="background: #f1f5f9;"' : 'required'}>
                    ${tag.is_system ? '<p style="font-size: 0.75rem; color: #94a3b8; margin-top: 0.25rem;">システムタグの名前は変更できません</p>' : ''}
                </div>
                <div class="tag-form-group">
                    <label>カラー</label>
                    <div class="tag-color-picker">
                        <input type="color" id="edit-tag-color-input" value="${tag.color}" onchange="updateEditTagColorPreview()">
                        <div id="edit-tag-color-preview" class="tag-color-preview" style="background-color: ${tag.color}; color: ${textColor};">
                            プレビュー
                        </div>
                    </div>
                </div>
                <div class="tag-form-group">
                    <label>説明 (任意)</label>
                    <input type="text" id="edit-tag-description-input" value="${escapeHtmlGlobal(tag.description || '')}">
                </div>
                <div style="display: flex; gap: 0.5rem; margin-top: 1rem;">
                    <button type="submit" class="btn btn-primary">保存</button>
                    <button type="button" class="btn btn-secondary" onclick="closeModal()">キャンセル</button>
                </div>
            </form>
        </div>
    `;

    showModal(modalHtml);
}

/**
 * Update tag color preview for edit modal
 */
function updateEditTagColorPreview() {
    const color = document.getElementById('edit-tag-color-input').value;
    const preview = document.getElementById('edit-tag-color-preview');
    const textColor = getContrastColor(color);
    preview.style.backgroundColor = color;
    preview.style.color = textColor;
}

/**
 * Update an existing tag
 */
async function updateTag(tagId) {
    const name = document.getElementById('edit-tag-name-input').value.trim();
    const color = document.getElementById('edit-tag-color-input').value;
    const description = document.getElementById('edit-tag-description-input').value.trim();

    try {
        const response = await fetch(`/api/tags/${tagId}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ name, color, description: description || null })
        });

        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.detail || 'Failed to update tag');
        }

        closeModal();
        await loadTagsManagement();
        alert('タグを更新しました');
    } catch (error) {
        alert(`エラー: ${error.message}`);
    }
}

/**
 * Delete a tag
 */
async function deleteTag(tagId) {
    const tag = allTags.find(t => t.id === tagId);
    if (!tag) return;

    if (!confirm(`タグ "${tag.name}" を削除しますか？\n\nこのタグを使用しているプロンプトからも削除されます。`)) {
        return;
    }

    try {
        const response = await fetch(`/api/tags/${tagId}`, {
            method: 'DELETE'
        });

        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.detail || 'Failed to delete tag');
        }

        await loadTagsManagement();
        alert(`タグ "${tag.name}" を削除しました`);
    } catch (error) {
        alert(`エラー: ${error.message}`);
    }
}

/**
 * Render model tags configuration
 */
async function renderModelTagsConfig() {
    const container = document.getElementById('model-tags-config');
    if (!container || !availableModelsData.length) {
        if (container) container.innerHTML = '<p style="color: #64748b;">モデルがありません</p>';
        return;
    }

    let html = '';
    for (const model of availableModelsData) {
        try {
            const response = await fetch(`/api/models/${model.name}/tags`);
            const modelTags = await response.json();

            const tagChips = modelTags.allowed_tags.map(tag => {
                const textColor = getContrastColor(tag.color);
                return `
                    <span class="tag-chip" style="background-color: ${tag.color}; color: ${textColor};">
                        ${escapeHtmlGlobal(tag.name)}
                        <span class="remove-tag" onclick="removeModelTag('${model.name}', ${tag.id})">×</span>
                    </span>
                `;
            }).join('');

            html += `
                <div class="model-tag-row">
                    <span class="model-name">${escapeHtmlGlobal(model.display_name)}</span>
                    <div class="model-tags">
                        ${tagChips}
                        <button class="btn-add-model-tag" onclick="showAddModelTagDropdown('${model.name}', this)">+ タグ追加</button>
                    </div>
                </div>
            `;
        } catch (error) {
            console.error(`Failed to load tags for model ${model.name}:`, error);
        }
    }

    container.innerHTML = html;
}

/**
 * Show dropdown to add tag to model
 */
function showAddModelTagDropdown(modelName, button) {
    // Remove existing dropdown
    const existingDropdown = document.querySelector('.model-tag-dropdown');
    if (existingDropdown) existingDropdown.remove();

    // Get current model tags
    fetch(`/api/models/${modelName}/tags`)
        .then(res => res.json())
        .then(modelTags => {
            const currentTagIds = new Set(modelTags.allowed_tag_ids);
            const availableTags = allTags.filter(t => !currentTagIds.has(t.id));

            if (availableTags.length === 0) {
                alert('追加可能なタグがありません');
                return;
            }

            const dropdown = document.createElement('div');
            dropdown.className = 'model-tag-dropdown tag-selector-dropdown';
            dropdown.style.cssText = 'position: absolute; z-index: 1000;';

            dropdown.innerHTML = availableTags.map(tag => {
                const textColor = getContrastColor(tag.color);
                return `
                    <div class="tag-selector-item" onclick="addModelTag('${modelName}', ${tag.id})">
                        <span class="tag-color-dot" style="background-color: ${tag.color};"></span>
                        <span>${escapeHtmlGlobal(tag.name)}</span>
                    </div>
                `;
            }).join('');

            // Position dropdown
            const rect = button.getBoundingClientRect();
            dropdown.style.top = (rect.bottom + window.scrollY) + 'px';
            dropdown.style.left = rect.left + 'px';

            document.body.appendChild(dropdown);

            // Close on click outside
            const closeDropdown = (e) => {
                if (!dropdown.contains(e.target) && e.target !== button) {
                    dropdown.remove();
                    document.removeEventListener('click', closeDropdown);
                }
            };
            setTimeout(() => document.addEventListener('click', closeDropdown), 10);
        });
}

/**
 * Add tag to model's allowed tags
 */
async function addModelTag(modelName, tagId) {
    try {
        // Get current tags
        const response = await fetch(`/api/models/${modelName}/tags`);
        const modelTags = await response.json();
        const newTagIds = [...modelTags.allowed_tag_ids, tagId];

        // Update tags
        await fetch(`/api/models/${modelName}/tags`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ tag_ids: newTagIds })
        });

        // Remove dropdown
        const dropdown = document.querySelector('.model-tag-dropdown');
        if (dropdown) dropdown.remove();

        await renderModelTagsConfig();
    } catch (error) {
        alert(`エラー: ${error.message}`);
    }
}

/**
 * Remove tag from model's allowed tags
 */
async function removeModelTag(modelName, tagId) {
    try {
        // Get current tags
        const response = await fetch(`/api/models/${modelName}/tags`);
        const modelTags = await response.json();
        const newTagIds = modelTags.allowed_tag_ids.filter(id => id !== tagId);

        if (newTagIds.length === 0) {
            alert('少なくとも1つのタグが必要です');
            return;
        }

        // Update tags
        await fetch(`/api/models/${modelName}/tags`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ tag_ids: newTagIds })
        });

        await renderModelTagsConfig();
    } catch (error) {
        alert(`エラー: ${error.message}`);
    }
}

/**
 * Get prompt tags for display
 */
async function getPromptTags(promptId) {
    try {
        const response = await fetch(`/api/prompts/${promptId}/tags`);
        return await response.json();
    } catch (error) {
        console.error('Failed to get prompt tags:', error);
        return [];
    }
}

/**
 * Render tag chips for a prompt
 */
function renderPromptTagChips(tags) {
    return tags.map(tag => {
        const textColor = getContrastColor(tag.color);
        return `<span class="prompt-tag-badge" style="background-color: ${tag.color}; color: ${textColor};">${escapeHtmlGlobal(tag.name)}</span>`;
    }).join(' ');
}

/**
 * Validate prompt tags against model before execution
 */
async function validatePromptTagsForModel(promptId, modelName) {
    try {
        const response = await fetch(`/api/validate-tags?prompt_id=${promptId}&model_name=${modelName}`);
        return await response.json();
    } catch (error) {
        console.error('Failed to validate tags:', error);
        return { valid: true, error: null }; // Fail open for safety
    }
}

// ========================================
// Prompt Editor Tag Management Functions
// ========================================

// Store current prompt tags in editor
let currentPromptEditorTags = [];

/**
 * Render tags in the prompt editor
 * @param {Array} tags - Array of tag objects with id, name, color
 */
function renderPromptEditorTags(tags) {
    currentPromptEditorTags = tags || [];
    const container = document.getElementById('prompt-editor-current-tags');
    if (!container) return;

    if (tags.length === 0) {
        container.innerHTML = '<span style="color: #94a3b8; font-size: 0.8rem;">タグなし (ALL扱い)</span>';
        return;
    }

    container.innerHTML = tags.map(tag => {
        const textColor = getContrastColor(tag.color);
        return `
            <span class="prompt-tag-chip" style="background-color: ${tag.color}; color: ${textColor};">
                ${escapeHtmlGlobal(tag.name)}
                <span class="remove-prompt-tag" onclick="removePromptEditorTag(${tag.id})" title="タグを削除">×</span>
            </span>
        `;
    }).join('');
}

/**
 * Show dropdown to add a tag to the prompt in editor
 * @param {HTMLElement} button - The button that triggered the dropdown
 */
async function showPromptEditorTagDropdown(button) {
    console.log('[TAG] showPromptEditorTagDropdown called');

    // Remove any existing dropdown
    const existingDropdown = document.querySelector('.prompt-tag-dropdown');
    if (existingDropdown) {
        console.log('[TAG] Removing existing dropdown');
        existingDropdown.remove();
        return;
    }

    // Load tags if not already loaded
    if (allTags.length === 0) {
        try {
            console.log('[TAG] Fetching tags...');
            const tagsResponse = await fetch('/api/tags');
            allTags = await tagsResponse.json();
            console.log('[TAG] Loaded', allTags.length, 'tags');
        } catch (error) {
            console.error('[TAG] Failed to load tags:', error);
            alert('タグの読み込みに失敗しました');
            return;
        }
    }

    // Get current tag IDs
    const currentTagIds = new Set(currentPromptEditorTags.map(t => t.id));
    const availableTags = allTags.filter(t => !currentTagIds.has(t.id));
    console.log('[TAG] Available tags:', availableTags.length);

    // Create dropdown
    const dropdown = document.createElement('div');
    dropdown.className = 'prompt-tag-dropdown';
    dropdown.id = 'prompt-editor-tag-dropdown';

    if (availableTags.length === 0) {
        dropdown.innerHTML = '<div class="prompt-tag-dropdown-empty">追加可能なタグがありません</div>';
    } else {
        dropdown.innerHTML = availableTags.map(tag => {
            return `
                <div class="prompt-tag-dropdown-item" data-tag-id="${tag.id}">
                    <span class="tag-dot" style="background-color: ${tag.color};"></span>
                    <span>${escapeHtmlGlobal(tag.name)}</span>
                </div>
            `;
        }).join('');
    }

    // Add click handlers to items
    dropdown.querySelectorAll('.prompt-tag-dropdown-item').forEach(item => {
        item.addEventListener('click', function(e) {
            e.stopPropagation();
            const tagId = parseInt(this.dataset.tagId);
            console.log('[TAG] Item clicked, tagId:', tagId);
            addPromptEditorTag(tagId);
            dropdown.remove();
        });
    });

    // Position dropdown
    const rect = button.getBoundingClientRect();
    dropdown.style.cssText = `
        position: fixed;
        top: ${rect.bottom + 4}px;
        left: ${rect.left}px;
        z-index: 10000;
        background: white;
        border: 1px solid #e2e8f0;
        border-radius: 8px;
        box-shadow: 0 4px 16px rgba(0,0,0,0.15);
        min-width: 200px;
        max-height: 300px;
        overflow-y: auto;
    `;

    document.body.appendChild(dropdown);
    console.log('[TAG] Dropdown appended at', rect.bottom + 4, rect.left);

    // Close on outside click (delayed to avoid immediate close)
    let canClose = false;
    setTimeout(() => { canClose = true; }, 300);

    function handleOutsideClick(e) {
        if (!canClose) return;
        if (!dropdown.contains(e.target) && e.target !== button && !button.contains(e.target)) {
            console.log('[TAG] Outside click, closing');
            dropdown.remove();
            document.removeEventListener('click', handleOutsideClick, true);
        }
    }

    document.addEventListener('click', handleOutsideClick, true);
}

/**
 * Add a tag to the current prompt in editor
 * @param {number} tagId - The tag ID to add
 */
async function addPromptEditorTag(tagId) {
    const promptId = document.getElementById('prompt-editor-prompt-id').value;
    if (!promptId) {
        alert('プロンプトを先に選択または保存してください');
        return;
    }

    // Close dropdown
    const dropdown = document.querySelector('.prompt-tag-dropdown');
    if (dropdown) dropdown.remove();

    try {
        const response = await fetch(`/api/prompts/${promptId}/tags/${tagId}`, {
            method: 'POST'
        });

        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.detail || 'Failed to add tag');
        }

        // Reload tags
        const tagsResponse = await fetch(`/api/prompts/${promptId}/tags`);
        if (tagsResponse.ok) {
            const tagsData = await tagsResponse.json();
            // API returns List[TagResponse] directly, not {tags: [...]}
            renderPromptEditorTags(Array.isArray(tagsData) ? tagsData : []);
        }
    } catch (error) {
        console.error('Failed to add tag:', error);
        alert('タグの追加に失敗しました: ' + error.message);
    }
}

/**
 * Remove a tag from the current prompt in editor
 * @param {number} tagId - The tag ID to remove
 */
async function removePromptEditorTag(tagId) {
    const promptId = document.getElementById('prompt-editor-prompt-id').value;
    if (!promptId) return;

    try {
        const response = await fetch(`/api/prompts/${promptId}/tags/${tagId}`, {
            method: 'DELETE'
        });

        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.detail || 'Failed to remove tag');
        }

        // Reload tags
        const tagsResponse = await fetch(`/api/prompts/${promptId}/tags`);
        if (tagsResponse.ok) {
            const tagsData = await tagsResponse.json();
            // API returns List[TagResponse] directly, not {tags: [...]}
            renderPromptEditorTags(Array.isArray(tagsData) ? tagsData : []);
        }
    } catch (error) {
        console.error('Failed to remove tag:', error);
        alert('タグの削除に失敗しました: ' + error.message);
    }
}

// ===========================================================
// Variable Picker for Workflow Control Flow
// ===========================================================

/**
 * Currently active variable picker target input
 */
let variablePickerTargetInput = null;

/**
 * Show variable picker dropdown for an input field
 * @param {HTMLElement} buttonEl - The button that was clicked
 */
function showVariablePicker(buttonEl) {
    const targetInput = buttonEl.previousElementSibling;
    if (!targetInput || (targetInput.tagName !== 'INPUT' && targetInput.tagName !== 'TEXTAREA')) {
        // Try to find input in parent's children
        const parent = buttonEl.parentElement;
        const input = parent.querySelector('input, textarea');
        if (!input) return;
        variablePickerTargetInput = input;
    } else {
        variablePickerTargetInput = targetInput;
    }

    // Get step context (which step this input belongs to)
    const stepDiv = buttonEl.closest('.workflow-step');
    const currentStepIndex = getStepIndex(stepDiv);

    // Build variable list
    const variables = buildVariableList(currentStepIndex);

    // Create or get picker dropdown
    let picker = document.getElementById('variable-picker-dropdown');
    if (!picker) {
        picker = document.createElement('div');
        picker.id = 'variable-picker-dropdown';
        picker.className = 'variable-picker-dropdown';
        document.body.appendChild(picker);
    }

    // Build dropdown content
    let html = '<div class="variable-picker-header">変数を挿入 / Insert Variable</div>';
    html += '<div class="variable-picker-content">';

    // Input parameters section
    if (variables.input.length > 0) {
        html += '<div class="variable-picker-section">';
        html += '<div class="variable-picker-section-title">入力パラメータ / Input Parameters</div>';
        for (const v of variables.input) {
            html += `<div class="variable-picker-item" onclick="insertVariable('${escapeHtmlGlobal(v.value)}')">`
                  + `<span class="variable-picker-item-name">${escapeHtmlGlobal(v.value)}</span>`
                  + `<span class="variable-picker-item-desc">${escapeHtmlGlobal(v.label)}</span></div>`;
        }
        html += '</div>';
    }

    // Variables section (from SET steps)
    if (variables.vars.length > 0) {
        html += '<div class="variable-picker-section">';
        html += '<div class="variable-picker-section-title">変数 / Variables (SET)</div>';
        for (const v of variables.vars) {
            html += `<div class="variable-picker-item" onclick="insertVariable('${escapeHtmlGlobal(v.value)}')">`
                  + `<span class="variable-picker-item-name">${escapeHtmlGlobal(v.value)}</span>`
                  + `<span class="variable-picker-item-desc">${escapeHtmlGlobal(v.label)}</span></div>`;
        }
        html += '</div>';
    }

    // Step outputs section
    if (variables.steps.length > 0) {
        html += '<div class="variable-picker-section">';
        html += '<div class="variable-picker-section-title">ステップ出力 / Step Outputs</div>';
        for (const v of variables.steps) {
            html += `<div class="variable-picker-item" onclick="insertVariable('${escapeHtmlGlobal(v.value)}')">`
                  + `<span class="variable-picker-item-name">${escapeHtmlGlobal(v.value)}</span>`
                  + `<span class="variable-picker-item-desc">${escapeHtmlGlobal(v.label)}</span></div>`;
        }
        html += '</div>';
    }

    // FOREACH item variable
    if (variables.foreach.length > 0) {
        html += '<div class="variable-picker-section">';
        html += '<div class="variable-picker-section-title">FOREACH 変数</div>';
        for (const v of variables.foreach) {
            html += `<div class="variable-picker-item" onclick="insertVariable('${escapeHtmlGlobal(v.value)}')">`
                  + `<span class="variable-picker-item-name">${escapeHtmlGlobal(v.value)}</span>`
                  + `<span class="variable-picker-item-desc">${escapeHtmlGlobal(v.label)}</span></div>`;
        }
        html += '</div>';
    }

    // Common patterns
    html += '<div class="variable-picker-section">';
    html += '<div class="variable-picker-section-title">共通パターン / Common Patterns</div>';
    html += `<div class="variable-picker-item" onclick="insertVariable('{{input.PARAM}}')">`
          + `<span class="variable-picker-item-name">{{input.PARAM}}</span>`
          + `<span class="variable-picker-item-desc">入力パラメータ</span></div>`;
    html += `<div class="variable-picker-item" onclick="insertVariable('{{vars.name}}')">`
          + `<span class="variable-picker-item-name">{{vars.name}}</span>`
          + `<span class="variable-picker-item-desc">SET変数</span></div>`;
    html += `<div class="variable-picker-item" onclick="insertVariable('{{stepN.result}}')">`
          + `<span class="variable-picker-item-name">{{stepN.result}}</span>`
          + `<span class="variable-picker-item-desc">ステップ出力</span></div>`;
    html += `<div class="variable-picker-item" onclick="insertVariable('sum({{a}}, {{b}})')">`
          + `<span class="variable-picker-item-name">sum({{a}}, {{b}})</span>`
          + `<span class="variable-picker-item-desc">合計関数</span></div>`;
    html += '</div>';

    html += '</div>'; // End variable-picker-content

    picker.innerHTML = html;

    // Position picker near the button
    const rect = buttonEl.getBoundingClientRect();
    picker.style.top = (rect.bottom + window.scrollY + 5) + 'px';
    picker.style.left = (rect.left + window.scrollX) + 'px';
    picker.style.display = 'block';

    // Close picker when clicking outside
    setTimeout(() => {
        document.addEventListener('click', closeVariablePickerOnClickOutside);
    }, 10);
}

/**
 * Get the index of a step in the workflow
 * @param {HTMLElement} stepDiv - The step div element
 * @returns {number} - The step index (0-based)
 */
function getStepIndex(stepDiv) {
    if (!stepDiv) return -1;
    const container = document.getElementById('workflow-steps-container');
    if (!container) return -1;
    const steps = Array.from(container.querySelectorAll('.workflow-step'));
    return steps.indexOf(stepDiv);
}

/**
 * Build list of available variables for a step
 * @param {number} currentStepIndex - The current step index (0-based)
 * @returns {Object} - Variables grouped by category
 */
function buildVariableList(currentStepIndex) {
    const variables = {
        input: [],
        vars: [],
        steps: [],
        foreach: []
    };

    const container = document.getElementById('workflow-steps-container');
    if (!container) return variables;

    const steps = Array.from(container.querySelectorAll('.workflow-step'));

    // Get workflow input parameters from the workflow's prompt (first prompt step with input params)
    // For now, use a generic placeholder - actual params would need to be fetched from workflow config
    const workflowInputParams = getWorkflowInputParams();
    for (const param of workflowInputParams) {
        variables.input.push({
            value: `{{input.${param}}}`,
            label: param
        });
    }

    // Scan steps before current step
    for (let i = 0; i < currentStepIndex && i < steps.length; i++) {
        const step = steps[i];
        const stepName = step.querySelector('.step-name')?.value?.trim() || `step${i + 1}`;
        const stepType = step.querySelector('.step-type')?.value || 'prompt';

        if (stepType === 'set') {
            // Collect SET variable names
            const assignmentRows = step.querySelectorAll('.set-assignment-row');
            assignmentRows.forEach(row => {
                const varName = row.querySelector('.set-var-name')?.value?.trim();
                if (varName) {
                    variables.vars.push({
                        value: `{{vars.${varName}}}`,
                        label: `SET at ${stepName}`
                    });
                }
            });
        } else if (stepType === 'prompt') {
            // Add step output references
            variables.steps.push({
                value: `{{${stepName}.result}}`,
                label: `${stepName} の出力`
            });
            // Add common parsed fields
            variables.steps.push({
                value: `{{${stepName}.parsed}}`,
                label: `${stepName} のパース結果`
            });
        } else if (stepType === 'foreach') {
            // FOREACH item variable
            const itemVar = step.querySelector('.foreach-item-var')?.value?.trim() || 'item';
            const indexVar = step.querySelector('.foreach-index-var')?.value?.trim() || 'i';
            variables.foreach.push({
                value: `{{vars.${itemVar}}}`,
                label: `FOREACH 現在要素`
            });
            variables.foreach.push({
                value: `{{vars.${indexVar}}}`,
                label: `FOREACH インデックス`
            });
        }
    }

    return variables;
}

/**
 * Get workflow input parameters from the current workflow
 * @returns {Array<string>} - List of input parameter names
 */
function getWorkflowInputParams() {
    const params = [];

    // Try to get from loaded workflow
    const workflowId = document.getElementById('workflow-id')?.value;
    if (window.currentWorkflowInputParams && Array.isArray(window.currentWorkflowInputParams)) {
        return window.currentWorkflowInputParams;
    }

    // Scan all prompt steps for input mappings that reference input params
    const container = document.getElementById('workflow-steps-container');
    if (container) {
        container.querySelectorAll('.input-mapping-row').forEach(row => {
            const valueInput = row.querySelector('.mapping-value');
            if (valueInput) {
                const value = valueInput.value || '';
                const match = value.match(/\{\{input\.([^}]+)\}\}/);
                if (match && !params.includes(match[1])) {
                    params.push(match[1]);
                }
            }
        });

        // Also scan condition inputs for input references
        container.querySelectorAll('.condition-left, .condition-right, .set-var-value, .foreach-source').forEach(input => {
            const value = input.value || '';
            const matches = value.matchAll(/\{\{input\.([^}]+)\}\}/g);
            for (const match of matches) {
                if (!params.includes(match[1])) {
                    params.push(match[1]);
                }
            }
        });
    }

    return params;
}

/**
 * Insert a variable into the target input
 * @param {string} variable - The variable string to insert
 */
function insertVariable(variable) {
    if (!variablePickerTargetInput) return;

    const input = variablePickerTargetInput;
    const start = input.selectionStart || 0;
    const end = input.selectionEnd || 0;
    const currentValue = input.value || '';

    // Insert variable at cursor position
    const newValue = currentValue.substring(0, start) + variable + currentValue.substring(end);
    input.value = newValue;

    // Set cursor position after inserted variable
    const newPos = start + variable.length;
    input.setSelectionRange(newPos, newPos);
    input.focus();

    // Close picker
    closeVariablePicker();

    // Trigger input event for any listeners
    input.dispatchEvent(new Event('input', { bubbles: true }));
}

/**
 * Close the variable picker dropdown
 */
function closeVariablePicker() {
    const picker = document.getElementById('variable-picker-dropdown');
    if (picker) {
        picker.style.display = 'none';
    }
    variablePickerTargetInput = null;
    document.removeEventListener('click', closeVariablePickerOnClickOutside);
}

/**
 * Close variable picker when clicking outside
 * @param {Event} event - The click event
 */
function closeVariablePickerOnClickOutside(event) {
    const picker = document.getElementById('variable-picker-dropdown');
    if (picker && !picker.contains(event.target) && !event.target.classList.contains('btn-var-insert')) {
        closeVariablePicker();
    }
}

/**
 * Create a variable insert button HTML
 * @returns {string} - HTML for the button
 */
function createVarInsertButton() {
    return `<button type="button" class="btn-var-insert" onclick="showVariablePicker(this)" title="変数を挿入 / Insert Variable">{...}</button>`;
}
