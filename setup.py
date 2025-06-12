from setuptools import setup, find_packages

setup(
    name="lead_processing_manager",
    version="0.1.0",
    package_dir={"": "src"},
    packages=find_packages(where="src"),
    install_requires=[
        # Add your project dependencies here
        "sqlalchemy",
        "pandas",
        "openpyxl",
        "python-dotenv",
        "openai",
        "python-telegram-bot",
        "google-api-python-client",
        "google-auth-oauthlib",
        "google-auth-httplib2",
        "schedule",
        "email-validator",
        "requests",
        "urllib3",
        "flask"
    ],
    author="Nikita Voronkin",
    description="A tool for managing and processing sales leads",
    python_requires=">=3.6",
)
