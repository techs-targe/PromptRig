# PromptRig

**A Local Web Application for Evaluating and Benchmarking LLM Prompts**

![License](https://img.shields.io/badge/license-MIT-blue.svg)
![Python](https://img.shields.io/badge/python-3.10%2B-blue.svg)

---

## 📖 Overview

PromptRig is a comprehensive prompt evaluation and benchmarking system designed for developers and researchers working with Large Language Models (LLMs). It provides a local web interface to test, evaluate, and compare prompt templates across multiple LLM models.

### Key Features

✅ **Multiple LLM Support**
- Azure OpenAI (GPT-4.1, GPT-5-mini, GPT-5-nano)
- OpenAI (GPT-4.1-nano)
- Easy model configuration and switching

✅ **Project Management**
- Multiple projects with independent configurations
- Prompt template versioning (revision tracking)
- Custom response parsers (JSON Path, Regex)

✅ **Execution Modes**
- **Single Execution**: Test prompts with manual input
- **Batch Execution**: Process datasets from Excel files
- Repeated execution for statistical analysis

✅ **Data Management**
- Excel dataset import (.xlsx with named ranges)
- Dynamic parameter substitution (`{{PARAM_NAME}}`)
- Support for multiple input types (TEXT, NUM, DATE, DATETIME)

✅ **Advanced Features**
- Response parsing with JSON Path and Regex
- CSV export of batch results
- Execution history with turnaround time tracking
- Configurable model parameters (temperature, max_tokens, top_p)

---

## 🚀 Quick Start

### Windows (One-Click Setup)

1. **Download and Install Python 3.10-3.12**
   - [Download Python](https://www.python.org/downloads/)
   - ⚠️ Check "Add Python to PATH" during installation

2. **Clone Repository**
   ```cmd
   git clone https://github.com/techs-targe/PromptRig.git
   cd PromptRig
   ```

3. **Run Setup**
   - Double-click `setup.bat`

4. **Configure API Keys**
   - Edit `.env` file with your Azure OpenAI / OpenAI credentials

5. **Start Application**
   - Double-click `run.bat`
   - Open http://localhost:9200 in your browser

### Linux / macOS

```bash
git clone https://github.com/techs-targe/PromptRig.git
cd PromptRig
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# Edit .env with your API keys
python main.py
```

See [INSTALL.md](INSTALL.md) for detailed installation instructions.

---

## 💡 Usage

### 1. Single Execution

Test prompts with manual parameter input:

1. Navigate to **単発実行 / Single Execution** tab
2. Select your project and model
3. Click **プロンプト編集 / Edit Prompt** to define template:
   ```
   Analyze the following text and provide insights:
   
   Text: {{text:TEXT10}}
   Focus Area: {{focus:TEXT5}}
   ```
4. Fill in parameter values
5. Click **1件送信 / Send Once** or **n回送信 / Send n Times**

### 2. Batch Execution

Process multiple rows from Excel datasets:

1. Navigate to **バッチ実行 / Batch Execution** tab
2. Import dataset: **データセットインポート / Import Dataset**
3. Select project, dataset, and model
4. Click **バッチ実行開始 / Start Batch**
5. Monitor progress and download CSV results

### 3. Project Management

Create and manage multiple evaluation projects:

1. Navigate to **プロジェクト設定 / Projects** tab
2. Click **新規プロジェクト作成 / Create Project**
3. Configure prompt templates and response parsers
4. Track revision history

### 4. System Settings

Configure default models and parameters:

1. Navigate to **システム設定 / System Settings** tab
2. Set default LLM model
3. Customize model parameters (temperature, max_tokens, top_p)
4. View available models

---

## 🛠️ Technology Stack

- **Backend**: Python 3.10-3.12, FastAPI, SQLAlchemy
- **Frontend**: HTML5, CSS3, Vanilla JavaScript
- **Database**: SQLite
- **LLM Integration**: Azure OpenAI, OpenAI
- **Server**: Uvicorn (ASGI)

---

## 📂 Project Structure

```
PromptRig/
├── main.py                 # Application entry point
├── requirements.txt        # Python dependencies
├── .env.example           # Environment template
├── setup.bat              # Windows setup script
├── run.bat                # Windows run script
├── INSTALL.md             # Installation guide
├── README.md              # This file
├── app/
│   ├── routes/            # API endpoints
│   ├── templates/         # HTML templates
│   └── static/            # CSS, JavaScript
├── backend/
│   ├── llm/               # LLM client modules
│   │   ├── azure_gpt_4_1.py
│   │   ├── azure_gpt_5_mini.py
│   │   ├── azure_gpt_5_nano.py
│   │   └── openai_gpt_4_nano.py
│   ├── database/          # Database models
│   ├── parser.py          # Response parsing
│   ├── prompt.py          # Template parsing
│   └── job.py             # Job management
└── database/              # SQLite database (auto-created)
```

---

## 🔧 Configuration

### Environment Variables (.env)

```bash
# Azure OpenAI
AZURE_OPENAI_ENDPOINT=https://your-resource.openai.azure.com/
AZURE_OPENAI_API_KEY=your-api-key
AZURE_OPENAI_DEPLOYMENT_NAME=your-deployment
AZURE_OPENAI_API_VERSION=2024-02-15-preview

# Optional: GPT-5 Models
AZURE_OPENAI_GPT5_MINI_DEPLOYMENT_NAME=gpt5-mini
AZURE_OPENAI_GPT5_NANO_DEPLOYMENT_NAME=gpt5-nano

# OpenAI (Optional)
OPENAI_API_KEY=your-openai-key

# Application
DATABASE_PATH=database/app.db
ACTIVE_LLM_MODEL=azure-gpt-4.1
```

### Supported Parameter Types

- `{{param}}` - Default: 5-line text area
- `{{param:TEXT5}}` - 5-line text area
- `{{param:TEXT10}}` - 10-line text area
- `{{param:NUM}}` - Number input
- `{{param:DATE}}` - Date picker
- `{{param:DATETIME}}` - DateTime picker

---

## 📊 Response Parsing

### JSON Path Parser

Extract structured data from JSON responses:

```json
{
  "type": "json_path",
  "paths": {
    "score": "$.evaluation.score",
    "feedback": "$.evaluation.feedback"
  },
  "csv_template": "$score$,$feedback$"
}
```

### Regex Parser

Extract data using regular expressions:

```json
{
  "type": "regex",
  "patterns": {
    "score": "Score:\\s*(\\d+)",
    "category": "Category:\\s*([A-Z]+)"
  }
}
```

---

## 🤝 Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

---

## 📄 License

This project is licensed under the MIT License - see the LICENSE file for details.

---

## 🐛 Troubleshooting

### Port Already in Use

Edit `main.py` to change the port:
```python
uvicorn.run(app, host="127.0.0.1", port=9201)
```

### Database Issues

Delete `database/` folder and restart the application.

### Virtual Environment Issues (Windows)

```cmd
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
```

For more troubleshooting, see [INSTALL.md](INSTALL.md).

---

## 📮 Contact

- **Author**: techs-targe
- **Email**: techs.targe@gmail.com
- **Repository**: https://github.com/techs-targe/PromptRig

---

## 🙏 Acknowledgments

Built with FastAPI, SQLAlchemy, and modern web technologies.

---

**Made with ❤️ for the LLM Developer Community**
