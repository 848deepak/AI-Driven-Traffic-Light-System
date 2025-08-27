# Contributing to AI Traffic Light Control System

Thank you for your interest in contributing to our AI-Driven Traffic Light Control System! This document provides guidelines for contributing to this project.

## Core Contributors

This project was developed by:
- **Deepak Pandey** (Team Leader)
- **Aayush**
- **Nidhi** 
- **Paisha**
- **Tanvi**

## Getting Started

1. **Fork the repository** on GitHub
2. **Clone your fork** to your local machine
3. **Set up the development environment** by installing dependencies from `requirements.txt`
4. **Create a branch** for your feature or bugfix

## Development Environment Setup

```bash
# Clone your fork
git clone https://github.com/your-username/AI-Driven-Traffic-Light-System.git
cd AI-Driven-Traffic-Light-System

# Create and activate a virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r ai-traffic-light/requirements.txt
```

## Contribution Workflow

1. **Make your changes** in your feature branch
2. **Test your changes** thoroughly
3. **Commit your changes** with clear commit messages
4. **Push to your fork** on GitHub
5. **Submit a pull request** to the main repository

## Coding Guidelines

Please follow these guidelines when contributing code:

- Follow [PEP 8](https://pep8.org/) styling guidelines
- Write docstrings for all functions, classes, and modules
- Include comments for complex logic
- Write unit tests for new features when applicable
- Ensure your code works on Raspberry Pi 5

## Pull Request Process

1. Update the README.md with details of changes if applicable
2. Update documentation if you're changing functionality
3. The PR should work on Raspberry Pi 5 hardware
4. PRs will be merged after review and approval

## Testing

Before submitting your PR, make sure to test your changes:

```bash
# Run the system with your changes
python run.py --test-mode --with-dashboard --verbose
```

Test with actual hardware when possible, or at minimum in test mode.

## Reporting Bugs

Please report bugs using the GitHub issue tracker with the following information:

- A clear, descriptive title
- Steps to reproduce the issue
- Expected behavior
- Actual behavior
- Screenshots if applicable
- System information (OS, Python version, hardware)

## Feature Requests

Feature requests are welcome! Please provide:

- A clear description of the feature
- Why it would be valuable
- Any implementation ideas you may have

## License

By contributing to this project, you agree that your contributions will be licensed under the project's [MIT License](LICENSE).

## Questions?

If you have any questions, feel free to open an issue with the "question" label or contact the maintainers directly.

Thank you for contributing to make traffic management smarter and more efficient! 