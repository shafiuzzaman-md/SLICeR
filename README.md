# SLICeR
Automated pipeline for CodeQL-based and LLM-assisted symbolic execution with KLEE.

## Prerequisites
### System packages
```
sudo apt update && sudo apt install -y \
    unzip wget git python3 python3-pip \
    build-essential autoconf automake libtool pkg-config \
    cmake zlib1g-dev liblzma-dev libicu-dev \
    git-lfs
```

### Compiler toolchain (LLVM/Clang 14):
```
sudo apt-get install -y llvm-14 clang-14 lldb-14 lld-14 clangd-14 libclang-14-dev

sudo update-alternatives --install /usr/bin/clang clang /usr/bin/clang-14 140 \
  --slave /usr/bin/clang++ clang++ /usr/bin/clang++-14 \
  --slave /usr/bin/clang-cpp clang-cpp /usr/bin/clang-cpp-14

sudo update-alternatives --install /usr/bin/llvm-link llvm-link /usr/lib/llvm-14/bin/llvm-link 140
sudo update-alternatives --install /usr/bin/opt       opt       /usr/lib/llvm-14/bin/opt       140

```
Verify:
```
clang --version
llvm-link --version
opt --version
```
All should print 14.0.6.

Python dependencies:
```
pip install --upgrade openai --break-system-packages
python3 -m pip install --user requests pyyaml --break-system-packages
```
## Build KLEE:
```
# Install dependencies
sudo apt-get update
sudo apt-get install -y libsqlite3-dev

mkdir -p ~/tools && cd ~/tools

# Build klee-uclibc
git clone https://github.com/klee/klee-uclibc.git
cd klee-uclibc
./configure --make-llvm-lib --with-cc clang-14 --with-llvm-config llvm-config-14
make -j2
cd ..

# Build KLEE
git clone https://github.com/klee/klee.git
cd klee
mkdir build && cd build

cmake .. \
  -DCMAKE_C_COMPILER=clang-14 \
  -DCMAKE_CXX_COMPILER=clang++-14 \
  -DLLVM_CONFIG=/usr/lib/llvm-14/bin/llvm-config \
  -DENABLE_POSIX_RUNTIME=ON \
  -DKLEE_UCLIBC_PATH="$HOME/tools/klee-uclibc" \
  -DENABLE_UNIT_TESTS=OFF \
  -DENABLE_SYSTEM_TESTS=OFF \
  -DENABLE_TCMALLOC=OFF \
  -DENABLE_STP=OFF \
  -DENABLE_METASMT=OFF

make -j$(nproc)
echo 'export PATH=$HOME/tools/klee/build/bin:$PATH' >> ~/.bashrc
source ~/.bashrc
```


Verify:

```
which klee
klee --version
ls ~/tools/klee/include/klee/klee.h
```
