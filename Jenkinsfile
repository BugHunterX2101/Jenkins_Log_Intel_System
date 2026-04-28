pipeline {
    agent any

    options {
        timestamps()
        disableConcurrentBuilds()
        buildDiscarder(logRotator(numToKeepStr: '10'))
    }

    environment {
        PIP_DISABLE_PIP_VERSION_CHECK = '1'
        PYTHONUTF8 = '1'
        VENV_DIR = '.venv'
    }

    stages {
        stage('Cleanup & Setup') {
            steps {
                echo "=== Starting Pipeline Build ==="
                script {
                    if (isUnix()) {
                        sh '''
                            set -e
                            echo "Removing old virtual environment..."
                            rm -rf ${VENV_DIR} || true
                            echo "Creating fresh virtual environment..."
                            python3 -m venv ${VENV_DIR} || python -m venv ${VENV_DIR}
                            echo "Virtual environment created successfully"
                        '''
                    } else {
                        bat '''
                            echo Removing old virtual environment...
                            if exist %VENV_DIR% rmdir /s /q %VENV_DIR%
                            echo Creating fresh virtual environment...
                            python -m venv %VENV_DIR%
                            echo Virtual environment created successfully
                        '''
                    }
                }
            }
        }

        stage('Bootstrap Python Tools') {
            steps {
                echo "=== Installing pip, setuptools, wheel ==="
                script {
                    if (isUnix()) {
                        sh '''
                            set -e
                            ${VENV_DIR}/bin/python -m pip install --upgrade pip setuptools wheel --quiet
                            ${VENV_DIR}/bin/python -m pip cache purge
                            echo "Python tools bootstrap complete"
                            ${VENV_DIR}/bin/python --version
                            ${VENV_DIR}/bin/pip --version
                        '''
                    } else {
                        bat '''
                            call %VENV_DIR%/Scripts/activate.bat
                            python -m pip install --upgrade pip setuptools wheel --quiet
                            python -m pip cache purge
                            echo Python tools bootstrap complete
                            python --version
                            pip --version
                        '''
                    }
                }
            }
        }

        stage('Install Base Dependencies') {
            steps {
                echo "=== Installing base dependencies (without dev extras) ==="
                script {
                    if (isUnix()) {
                        sh '''
                            set -e
                            ${VENV_DIR}/bin/python -m pip install -e . --verbose
                            echo "Base dependencies installed"
                        '''
                    } else {
                        bat '''
                            call %VENV_DIR%/Scripts/activate.bat
                            python -m pip install -e . --verbose
                            echo Base dependencies installed
                        '''
                    }
                }
            }
        }

        stage('Install Development Dependencies') {
            steps {
                echo "=== Installing dev dependencies ==="
                script {
                    if (isUnix()) {
                        sh '''
                            set -e
                            ${VENV_DIR}/bin/python -m pip install -e ".[dev]" --verbose
                            echo "Development dependencies installed"
                        '''
                    } else {
                        bat '''
                            call %VENV_DIR%/Scripts/activate.bat
                            python -m pip install -e ".[dev]" --verbose
                            echo Development dependencies installed
                        '''
                    }
                }
            }
        }

        stage('Prepare Test Output') {
            steps {
                echo "=== Preparing test output directory ==="
                script {
                    if (isUnix()) {
                        sh 'mkdir -p reports && echo "Test directory ready"'
                    } else {
                        bat 'if not exist reports mkdir reports && echo Test directory ready'
                    }
                }
            }
        }

        stage('Run Unit Tests') {
            steps {
                echo "=== Running pytest unit tests ==="
                script {
                    if (isUnix()) {
                        sh '''
                            set -e
                            ${VENV_DIR}/bin/python -m pytest --junitxml=reports/junit.xml --verbose
                        '''
                    } else {
                        bat '''
                            call %VENV_DIR%/Scripts/activate.bat
                            python -m pytest --junitxml=reports/junit.xml --verbose
                        '''
                    }
                }
            }
        }

        stage('Run Smoke Tests') {
            steps {
                echo "=== Running smoke tests ==="
                script {
                    if (isUnix()) {
                        sh '''
                            set -e
                            ${VENV_DIR}/bin/python -c "import main; print('✓ Main module imported'); print(f'✓ App title: {main.app.title}')"
                            echo "Smoke tests passed"
                        '''
                    } else {
                        bat '''
                            call %VENV_DIR%/Scripts/activate.bat
                            python -c "import main; print('✓ Main module imported'); print(f'✓ App title: {main.app.title}')"
                            echo Smoke tests passed
                        '''
                    }
                }
            }
        }
    }

    post {
        success {
            echo "=== BUILD SUCCESSFUL ==="
            archiveArtifacts artifacts: 'reports/**/*.xml', allowEmptyArchive: true
        }
        
        failure {
            echo "=== BUILD FAILED ===" 
            archiveArtifacts artifacts: 'reports/**/*.xml', allowEmptyArchive: true
        }
        
        always {
            junit testResults: 'reports/**/*.xml', allowEmptyResults: true
            script {
                if (isUnix()) {
                    sh 'echo "Build completed - checking environment..." && ${VENV_DIR}/bin/pip list | grep -E "fastapi|sqlalchemy|asyncpg" || true' 
                } else {
                    bat 'echo Build completed - checking environment... && call %VENV_DIR%/Scripts/activate.bat && pip list | findstr /C:"fastapi" /C:"sqlalchemy" /C:"asyncpg" || (echo No matches found)'
                }
            }
        }
    }
}
