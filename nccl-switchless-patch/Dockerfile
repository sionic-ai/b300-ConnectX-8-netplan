FROM ghcr.io/coreweave/nccl-tests:13.2.0-devel-ubuntu24.04-nccl2.29.7-1-7112046

ENV DEBIAN_FRONTEND=noninteractive
ENV NCCL_VERSION_TAG=v2.30.3-1
ENV NCCL_TESTS_TAG=v2.16.0
ENV CUDA_HOME=/usr/local/cuda

WORKDIR /opt

RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    ca-certificates \
    build-essential \
    pkg-config \
    python3 \
    python3-pip \
    libnuma-dev \
    libibverbs-dev \
    rdma-core \
 && rm -rf /var/lib/apt/lists/*

RUN git clone https://github.com/NVIDIA/nccl.git /opt/nccl
WORKDIR /opt/nccl
RUN git checkout ${NCCL_VERSION_TAG}

COPY nccl-switchless.patch /opt/nccl-switchless.patch
RUN git apply /opt/nccl-switchless.patch

RUN make -j"$(nproc)" src.build CUDA_HOME=${CUDA_HOME}

RUN find /usr -name 'libnccl.so*' -type f 2>/dev/null | xargs -r rm -f && \
    cp -av /opt/nccl/build/lib/libnccl.so* /usr/lib/x86_64-linux-gnu/ && \
    ldconfig

RUN mkdir -p /usr/include/nccl && \
    cp -av /opt/nccl/build/include/* /usr/include/nccl/ || true

RUN git clone https://github.com/NVIDIA/nccl-tests.git /opt/nccl-tests-src
WORKDIR /opt/nccl-tests-src
RUN git checkout ${NCCL_TESTS_TAG}

# 기본 compute_70 등을 쓰지 않도록 아키텍처 직접 지정
# B300/Blackwell
RUN make -j"$(nproc)" \
    MPI=0 \
    CUDA_HOME=${CUDA_HOME} \
    NCCL_HOME=/opt/nccl/build \
    NVCC_GENCODE="-gencode=arch=compute_100,code=sm_100 -gencode=arch=compute_100,code=compute_100"

RUN mkdir -p /opt/nccl-tests/build && \
    cp -av /opt/nccl-tests-src/build/* /opt/nccl-tests/build/

ENV NCCL_IB_SWITCHLESS=1
ENV NCCL_IB_SWITCHLESS_PREFIX=30

WORKDIR /workspace
CMD ["/bin/bash"]
