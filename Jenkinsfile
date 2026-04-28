pipeline {
    agent any

    options {
        timestamps()
        disableConcurrentBuilds()
    }

    environment {
        PIP_DISABLE_PIP_VERSION_CHECK = '1'
        PYTHONUTF8 = '1'
    }

    stages {
        stage('Checkout') {
            steps {
                script {
                    if (isUnix()) {
                        sh 'git clone --branch main https://github.com/BugHunterX2101/Jenkins_Log_Intel_System.git .'
                    } else {
                        bat 'git clone --branch main https://github.com/BugHunterX2101/Jenkins_Log_Intel_System.git .'
                    }
                }
            }
        }

        stage('Bootstrap Python') {
            steps {
                script {
                    if (isUnix()) {
                        sh '''
                            set -e
                            python3 -m venv .venv || python -m venv .venv
                            .venv/bin/python -m pip install --upgrade pip setuptools wheel
                        '''
                    } else {
                        bat '''
                            if not exist .venv (
                                python -m venv .venv
                            )
                            call .venv/Scripts/activate.bat
                            python -m pip install --upgrade pip setuptools wheel
                        '''
                    }
                }
            }
        }

        stage('Install Dependencies') {
            steps {
                script {
                    if (isUnix()) {
                        sh '.venv/bin/python -m pip install -e ".[dev]"'
                    } else {
                        bat '''
                            call .venv/Scripts/activate.bat
                            python -m pip install -e ".[dev]"
                        '''
                    }
                }
            }
        }

        stage('Prepare Test Output') {
            steps {
                script {
                    if (isUnix()) {
                        sh 'mkdir -p reports'
                    } else {
                        bat 'if not exist reports mkdir reports'
                    }
                }
            }
        }

        stage('Run Tests') {
            steps {
                script {
                    if (isUnix()) {
                        sh '.venv/bin/python -m pytest --junitxml=reports/junit.xml'
                    } else {
                        bat '''
                            call .venv/Scripts/activate.bat
                            python -m pytest --junitxml=reports/junit.xml
                        '''
                    }
                }
            }
        }

        stage('Smoke Test') {
            steps {
                script {
                    if (isUnix()) {
                        sh '.venv/bin/python -c "import main; print(main.app.title)"'
                    } else {
                        bat '''
                            call .venv/Scripts/activate.bat
                            python -c "import main; print(main.app.title)"
                        '''
                    }
                }
            }
        }
    }

    post {
        always {
            archiveArtifacts artifacts: 'reports/**/*.xml', allowEmptyArchive: true
            junit testResults: 'reports/**/*.xml', allowEmptyResults: true
        }
    }
}
