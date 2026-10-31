# Run only in a disposable container; the opt-in tests create system users.
# From the repository root:
# docker build -t qwenpaw-hub-ownership-tests tests/fixtures/hub/docker-ownership
# docker run --rm --network none --security-opt no-new-privileges:true \
#   --mount "type=bind,src=$PWD,dst=/repo,readonly" qwenpaw-hub-ownership-tests
FROM python:3.11-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends python3 supervisor gettext-base passwd \
    && rm -rf /var/lib/apt/lists/*
RUN python -m pip install --no-cache-dir \
    pytest pytest-asyncio pyyaml pydantic httpx python-dotenv docker cryptography

ENV QWENPAW_TEST_DOCKER_OWNERSHIP=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/repo/src \
    QWENPAW_DEPENDENCY_STATE_DIR=/tmp/qwenpaw-test-state \
    QWENPAW_WORKING_DIR=/tmp/qwenpaw-test-working \
    QWENPAW_SECRET_DIR=/tmp/qwenpaw-test-secrets
WORKDIR /repo
CMD ["python", "-m", "pytest", "--noconftest", "-p", "no:cacheprovider", \
     "tests/unit/scripts/test_docker_runtime_user.py", \
     "tests/unit/hub/test_service.py", \
     "tests/unit/hub/test_docker_provisioner.py", \
     "tests/unit/utils/test_io_utils.py", "-q"]
