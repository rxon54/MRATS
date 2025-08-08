# Project Requirements Document - Web Transcriber Upgrade

## Project Title: Web Transcriber - Local LLM Integration & Automation

**Version:** 1.0
**Date:** October 26, 2023
**Author:** [Your Name/Alias]

## 1. Introduction

This document outlines the requirements for upgrading the web transcriber project. The primary goals are to enhance privacy by 
utilizing a local Large Language Model (LLM) (OlaMa), automate the transcription and polishing workflow, and improve the user 
interface.

## 2. Functional Requirements

### 2.1. Local LLM Integration (OlaMa)

*   **Requirement:** Integrate OlaMa as a local module within the project.
*   **Details:** Replace any external LLM services (e.g., OpenAI) with a local OlaMa instance. This is crucial for maintaining 
data privacy, given the existing local Whisper C++ setup.
*   **Research:** Investigate and implement a mechanism to keep the OlaMa model loaded in memory for continuous availability and 
faster processing.

### 2.2. Automated Workflow

*   **Requirement:** Automate the transcription and polishing process.
*   **Details:**
    *   **Initiation:** Transcription should automatically start upon receiving a new audio file via the API from the iPhone.
    *   **Polishing:** Upon transcription completion, trigger a large language model (LLM) polishing process.
    *   **Output:** The polishing process should generate a Markdown (.md) file containing the polished transcription.

### 2.3. User Interface (UI) Enhancements

*   **Requirement:** Improve the user interface for better usability.
*   **Details:**
    *   **Sorting:** Implement proper sorting of transcriptions by date in the UI.
    *   **Audit Trail:** Include a dedicated audit trail section on the left side of the UI.
    *   **Obsidian Integration:** Add a button to easily send transcriptions to Obsidian.
    *   **Syncing:** Explore and implement a solution for syncing the Obsidian vault folder across multiple laptops (e.g., using 
SSH or a dedicated syncing service).

## 3. Non-Functional Requirements

*   **Performance:** The local LLM integration should not significantly impact the overall transcription speed.
*   **Maintainability:** The codebase should remain maintainable and well-documented.
*   **Scalability:** The architecture should be scalable to accommodate future features and increased usage.
*   **Privacy:** Ensure all data processing remains local to maintain user privacy.

## 4. Technical Considerations

*   **Language:** [Specify the primary programming language(s) used in the project - e.g., Python, JavaScript]
*   **Dependencies:** [List any key dependencies - e.g., Whisper C++, OlaMa, API libraries]
*   **API:** The project utilizes an API for receiving audio files from the iPhone.

## 5. Future Considerations

*   Explore integration with other productivity tools.
*   Implement advanced features like speaker diarization.
*   Develop a user configuration panel for customizing the polishing process.
