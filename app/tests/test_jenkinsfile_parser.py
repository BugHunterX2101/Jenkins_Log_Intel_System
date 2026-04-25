"""Unit tests for the Jenkinsfile parser."""

import pytest
from app.services.jenkinsfile_parser import parse_stages, _raw_url


def test_parse_declarative_pipeline():
    jf = """
pipeline {
    agent any
    stages {
        stage('Checkout') { steps { checkout scm } }
        stage('Test')     { steps { sh 'pytest' } }
        stage('Build')    { steps { sh 'docker build .' } }
        stage('Deploy')   { steps { sh './deploy.sh' } }
    }
}
"""
    stages = parse_stages(jf)
    assert stages == ['Checkout', 'Test', 'Build', 'Deploy']


def test_parse_scripted_pipeline():
    jf = """
node {
    stage("Checkout") { checkout scm }
    stage("Unit Tests") { sh 'pytest' }
    stage("Package") { sh 'mvn package' }
}
"""
    stages = parse_stages(jf)
    assert stages == ['Checkout', 'Unit Tests', 'Package']


def test_parse_mixed_quotes():
    jf = """stage('Single') { } \n stage("Double") { }"""
    stages = parse_stages(jf)
    assert stages == ['Single', 'Double']


def test_parse_deduplicates():
    jf = """
stage('Test') {
    parallel {
        stage('Test') { sh 'pytest a' }
        stage('Test') { sh 'pytest b' }
    }
}
"""
    stages = parse_stages(jf)
    assert stages == ['Test']


def test_parse_empty_jenkinsfile():
    assert parse_stages("pipeline { agent any }") == []


def test_parse_preserves_order():
    names = [f"Stage {i}" for i in range(10)]
    jf = "\n".join(f"stage('{n}') {{}}" for n in names)
    assert parse_stages(jf) == names


def test_raw_url_github():
    url = _raw_url("https://github.com/acme/my-repo", "main")
    assert url == "https://raw.githubusercontent.com/acme/my-repo/main/Jenkinsfile"


def test_raw_url_github_dotgit():
    url = _raw_url("https://github.com/acme/my-repo.git", "feature/x")
    assert "raw.githubusercontent.com" in url
    assert "feature/x" in url


def test_raw_url_gitlab():
    url = _raw_url("https://gitlab.com/acme/my-repo", "main")
    assert url is not None
    assert "gitlab.com/api/v4" in url
    assert "Jenkinsfile" in url


def test_raw_url_bitbucket():
    url = _raw_url("https://bitbucket.org/acme/my-repo.git", "develop")
    assert url is not None
    assert "bitbucket.org" in url


def test_raw_url_ssh_returns_none():
    url = _raw_url("git@github.com:acme/repo.git", "main")
    assert url is None


def test_raw_url_unknown_host_returns_none():
    url = _raw_url("https://internal-git.corp.example.com/acme/repo", "main")
    assert url is None
