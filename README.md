# QE-GenAI Framework

A modular Python framework for building GenAI applications with connectors, tokenizers, pipelines, and utilities.

## Table of Contents
1. [Features](#features)
2. [Installation](#installation)
3. [Usage](#usage)
4. [Folder Structure](#folder-structure)
5. [Dependencies](#dependencies)
6. [Contributing](#contributing)
7. [License](#license)


## Features
- **Connectors**: Easy-to-use connectors for GPT APIs, databases, and spreadsheets.
- **Tokenizers**: Tokenize text and image data using LangChain tools.
- **Pipelines**: Modular workflows like Retrieval-Augmented Generation (RAG).
- **Utilities**: Logging, configuration management, and helper tools.

### **Connectors**
Connectors are responsible for integrating with various external systems like GPT APIs, databases, and spreadsheets.

| **Connector**            | **Purpose**                                               |
|---------------------------|-----------------------------------------------------------|
| **GPTGatewayConnector**   | Manages interactions with GPT APIs via Azure API Gateway. |
| **DBConnector**           | Handles database connections using SQLAlchemy.            |
| **SpreadsheetConnector**  | Integrates with spreadsheet tools like Excel or CSV.      |

**Note**: Ensure connectors are interface-driven for easy extension to new data sources.

### **Tokenizers**
Tokenizers break data into smaller, manageable chunks for processing. The framework uses LangChain's tokenization tools.

| **Tokenizer**            | **Purpose**                                  |
|---------------------------|----------------------------------------------|
| **TextTokenizer**         | Splits textual data into chunks.            |
| **ImageTokenizer**        | Converts image inputs into embeddings.      |

**Note**: Tokenizers follow a consistent API for scalability. Support for additional modalities like audio and video can be added easily.


### **Completion Generators**
Completion Generators process input data and generate outputs using different techniques and pipelines.

| **Pipeline**             | **Purpose**                                      |
|---------------------------|-------------------------------------------------|
| **RAGPipeline**           | Implements Retrieval-Augmented Generation.      |
| **TestCaseGenerator**     | Generates test cases based on inputs.           |
| **UseCase2Generator**     | Handles specific use case generation logic.     |

**Note**: These modules are **loosely coupled** and can be tested or extended independently.


### **Model Accuracy**
This component evaluates the quality of model outputs using standard metrics.

| **Module**               | **Purpose**                                      |
|---------------------------|-------------------------------------------------|
| **BELUCalculator**        | Measures text generation quality using BLEU.    |
| **AccuracyReport**        | Generates structured accuracy metrics.          |

**Note**: Additional evaluation metrics like **ROUGE** and **METEOR** can be included for task-specific evaluation.


### **Utilities**
Utilities provide support functions that ensure smooth execution and consistency across the framework.

| **Utility**              | **Purpose**                                      |
|---------------------------|-------------------------------------------------|
| **Logger**                | Standardized logging for all components.        |
| **AccuracyReport**        | Redundant; ensure this is a single utility.     |

**Note**: Utility modules like `Logger` and `ConfigManager` should be centralized for reusability.





## Installation

1. Clone the repository:
   ```bash
   git clone https://github.com/yourusername/qe-genai-framework.git
   cd qe-genai-framework
   


Advantages of This Design
	1.	Prompt Engineering:
	•	Uses carefully crafted prompts to generate high-quality test cases.
	2.	Format Flexibility:
	•	Handles multiple formats (plain text, BDD, custom) with easy extensions for additional formats.
	3.	RAG Architecture:
	•	Combines retrieval and generation for context-aware test case creation.
	4.	LangChain Integration:
	•	Modular and scalable pipeline for embedding, querying, and generation.
	5.	Persistent Storage:
	•	Automatically stores generated test cases in the embedding store for future use.# pncgenai
