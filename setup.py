"""Setup script for AWS Tag Manager CLI."""

from setuptools import setup, find_packages
import os
import re

# Get version from __init__.py
def get_version():
    try:
        init_file = os.path.join("tag_manager_cli", "__init__.py")
        with open(init_file, "r", encoding="utf-8") as f:
            content = f.read()
            version_match = re.search(r'__version__\s*=\s*["\']([^"\']*)["\']', content)
            if version_match:
                version = version_match.group(1)
                # Handle LOCAL version for development/CI builds
                if version == "LOCAL":
                    return "0.0.0.dev0"

                # Handle git commit hashes (7-character hex strings)
                if re.match(r'^[a-f0-9]{7}$', version):
                    return f"0.0.0.dev0+{version}"

                # Handle semantic versions (v1.2.3 or 1.2.3)
                if version.startswith('v') and re.match(r'^v\d+\.\d+\.\d+', version):
                    return version[1:]  # Remove 'v' prefix

                # If it looks like a semantic version already, return as-is
                if re.match(r'^\d+\.\d+\.\d+', version):
                    return version

                # Fallback: treat as development version
                return f"0.0.0.dev0+{version}"

    except (FileNotFoundError, AttributeError):
        pass
    return "0.0.0.dev0"

# Try to read README.md, fallback to a default description
try:
    with open("README.md", "r", encoding="utf-8") as fh:
        long_description = fh.read()
except FileNotFoundError:
    long_description = "AWS Tag Manager CLI for Cost Allocation, Resource Organization, and Automated Tagging"

# Try to read requirements.txt, fallback to basic requirements
try:
    with open("requirements.txt", "r", encoding="utf-8") as fh:
        requirements = [line.strip() for line in fh if line.strip() and not line.startswith("#")]
except FileNotFoundError:
    requirements = [
        "typer>=0.9.0",
        "boto3>=1.34.0",
        "rich<14.3.0",
        "redis>=5.0.0",
        "celery>=5.3.0",
        "psycopg2-binary>=2.9.0",
        "sqlalchemy>=2.0.0",
        "alembic>=1.12.0"
    ]

setup(
    name="bluearch-aws-tags",
    version=get_version(),
    author="BlueArch",
    author_email="",
    description="AWS Tag Manager CLI for Cost Allocation, Resource Organization, and more",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/bluearchio/bluearch-aws-tags",
    license="MIT",
    packages=find_packages(),
    package_data={
        "tag_manager_cli.integrations": ["iam-policy.json"],
        "tag_manager_cli.web": ["static/**/*"],
    },
    classifiers=[
        "Development Status :: 3 - Alpha",
        "Intended Audience :: Developers",
        "Intended Audience :: System Administrators",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
        "Topic :: System :: Systems Administration",
        "Topic :: Utilities",
    ],
    python_requires=">=3.10",
    install_requires=requirements,
    entry_points={
        "console_scripts": [
            "bluearch-aws-tags=tag_manager_cli.main:cli",
            "tag-manager=tag_manager_cli.main:cli",
        ],
    },
    include_package_data=True,
    zip_safe=False,
)
