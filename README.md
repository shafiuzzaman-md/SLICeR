# SAILR: Static-Analysis guided Iterative LLM Refinement of Symbolic-Execution Harnesses
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
### Build KLEE:
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
### Install CodeQL
```
python3 install_codeql.py
source ~/.bashrc
```
## Extract dataset (example)
Source code:
```
python3 extract_from_cybergym.py arvo:62911 libxml2
```
Metadata for ground truth:
```
python3 fetch_cybergym_data.py --repo-dir ./cybergym_data arvo:61337
```
## Stattin Analysis Phase
### Download queries (example)
```
codeql pack install rules/uaf-pack \
  --search-path "/home/shafi/codeql-cli/codeql:/home/shafi/.codeql/packages"
```
### Run CodeQL (example)
```
./01_codeql_scan.sh \
  PROJECT_NAME=libxml2_66502_vul \
  SRC_ROOT=./dataset/66502/libxml2_66502_vul \
  BUILD_CMD="./build.sh" \
  QUERY_SUITES="rules/uaf-pack/suites/uaf.qls" \
  CONTEXT_LINES=5 \
  ALSO_CPP=false
```

### Extract Vul Specs from CodeQL findings
python3 scripts/make_vul_specs.py --findings sa/findings.json --facts sa/fact_pack.json --out out/specs

# 2) Seed (driver + seed plan)
python3 scripts/loopA_build_to_green.py \
  --spec out/specs/000_dict.c_541_local.oob.memfunc.length-misuse.json \
  --ccdb sa/compile_commands.json --settings config/settings.yaml

# 3) Enrich plan (fills in_path/helpers/symbolic; normalizes paths)
python3 scripts/plan_enrich.py \
  --plan out/plans/plan_dict.c_541.json \
  --spec out/specs/000_dict.c_541_local.oob.memfunc.length-misuse.json \
  --facts sa/fact_pack.json --ccdb sa/compile_commands.json \
  --src-root ../../../dataset/62911/libxml2_62911_vul --rewrite-driver

export DEEPSEEK_API_KEY=""

python3 scripts/synth_stubs.py \
  --plan out/plans/plan_dict.c_541.json \
  --spec out/specs/000_dict.c_541_local.oob.memfunc.length-misuse.json \
  --facts sa/fact_pack.json \
  --src-root ../../../dataset/62911/libxml2_62911_vul --rewrite-driver\
  --out out/plans/stub_plan_dict.c_541.json

python3 scripts/make_groom_seed.py \
  --plan out/plans/plan_dict.c_541.json \
  --stub-plan out/plans/stub_plan_dict.c_541.json \
  --out out/groom/groom_seed.json

python3 scripts/llm_synthesize_groom.py   --seed out/groom/groom_seed.json   --out  out/groom/groom_plan.json   --provider openai   --api-base https://api.deepseek.com   --api-key-env DEEPSEEK_API_KEY   --model deepseek-chat   --examples scripts/groom_examples.json


python3 scripts/instrument_inpath_and_stub.py \
  --plan out/plans/plan_dict.c_541.json \
  --spec out/specs/000_dict.c_541_local.oob.memfunc.length-misuse.json \
  --src-root ../../../dataset/62911/libxml2_62911_vul \
  --build-root out/build/instrumented \
  --stub-plan out/plans/stub_plan_dict.c_541.json \
  --groom-plan out/groom/groom_plan.json \
  --emit-groom \
  --require-llm-groom \
  --update-plan

# 4) Inject assertions into the *instrumented* file
python3 scripts/derive_assertion_and_inject.py \
  --spec out/specs/000_dict.c_541_local.oob.memfunc.length-misuse.json \
  --plan out/plans/plan_dict.c_541.json \
  --src-root ../../../dataset/62911/libxml2_62911_vul \
  --build-root out/build/instrumented \
  --inplace \
  --provider deepseek \
  --api-base https://api.deepseek.com \
  --model deepseek-chat \
  --examples scripts/assertion_examples.json \
  --strict


# 5) Build loop (must consume instrumented file from step 4)
python3 scripts/loopB_run_cegir.py \
  --plan out/plans/plan_dict.c_541.json \
  --ccdb sa/compile_commands.json \
  --build-root out/build

  
