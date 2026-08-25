#! /bin/bash

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" >/dev/null && pwd )"

EA="-ea"
#MONO="-Djava.library.path=$SCRIPT_DIR/monosat/libmonosat.so -cp $SCRIPT_DIR/monosat/monosat.jar"
#MONO="-cp $SCRIPT_DIR/monosat/"

# $COBRA_HOME/env.sh supplies CUDA_PATH and the fail() helper used by the GPU
# build. King Cobra runs on the CPU without any of that, so a missing
# COBRA_HOME is a warning rather than a hard stop.
if [ -n "$COBRA_HOME" ] && [ -f "$COBRA_HOME/env.sh" ]; then
  source $COBRA_HOME/env.sh
else
  echo "[warn] COBRA_HOME is not set, or env.sh is missing; continuing without it."
  echo "[warn] Use a config with GPU_MATRIX=false, such as ./cobra.conf.cpu"
fi

# env.sh normally defines fail(); supply one if it did not.
type fail >/dev/null 2>&1 || function fail {
  echo "$1"
  exit 1
}


function usage {
  echo " Usage: run.sh mono [audit|continue|epoch|ep-remote] <config> <traces>"
  echo " Usage: run mono dump <config path> <benchmark path> <dumpgraph path>"
  echo " Usage: run.sh build"
  echo " Usage: run.sh perf (=run.sh cobra continue)"
}


# The JNI build compiles Cobra's CUDA kernels, which needs nvcc. Without it the
# CPU reachability path still works, so skip rather than fail.
function buildJNI {
  if [ "$CUDA_PATH" == "" ] || ! command -v nvcc >/dev/null 2>&1; then
    echo "[warn] nvcc or CUDA_PATH not found; skipping the GPU (JNI) build."
    echo "[warn] Run with GPU_MATRIX=false, such as ./cobra.conf.cpu"
    return 0
  fi
  ./jni.sh || fail "build jni"
  echo "JNI build done"
}

if [ "$1" == "build" ]; then
  buildJNI
  mvn install || fail "mvn install"
  exit 0
fi


if [ "$1" == "perf" ]; then
  PROF="-agentlib:hprof=file=hprof.txt,cpu=samples"
  time java $EA $PROF -Djava.library.path=$SCRIPT_DIR/include/ -jar \
    target/CobraVerifier-0.0.1-SNAPSHOT-jar-with-dependencies.jar cobra audit || fail "FAIL: java benchmark"
fi

if [ "$1" != "mono" ]; then
  usage
  exit 1
fi

if [ "$2" != "audit" ] && [ "$2" != "continue" ] && [ "$2" != "epoch" ] && [ "$2" != "ep-remote" ] && [ "$2" != "dump" ]; then
  usage
  exit 1
fi

CONFIG_PATH=$3
if [ "$CONFIG_PATH" == "-" ]; then
  CONFIG_PATH="$SCRIPT_DIR/cobra.conf"
fi


if [ "$#"  == "2" ]; then
  time java $EA $MONO -Djava.library.path=$SCRIPT_DIR/include/ -jar \
    target/CobraVerifier-0.0.1-SNAPSHOT-jar-with-dependencies.jar "$1" "$2" || fail "FAIL: java benchmark"
fi

if [ "$#"  == "3" ]; then
  time java $EA $MONO -Djava.library.path=$SCRIPT_DIR/include/ -jar \
    target/CobraVerifier-0.0.1-SNAPSHOT-jar-with-dependencies.jar "$1" "$2" "$CONFIG_PATH" || fail "FAIL: java benchmark"
fi

if [ "$#"  == "4" ]; then
  time java $EA $MONO -Djava.library.path=$SCRIPT_DIR/include/ -jar \
    target/CobraVerifier-0.0.1-SNAPSHOT-jar-with-dependencies.jar "$1" "$2" "$CONFIG_PATH" "$4"|| fail "FAIL: java benchmark"
fi

if [ "$#"  == "5" ]; then
  time java $EA $MONO -Djava.library.path=$SCRIPT_DIR/include/ -jar \
    target/CobraVerifier-0.0.1-SNAPSHOT-jar-with-dependencies.jar "$1" "$2" "$CONFIG_PATH" "$4" "$5"|| fail "FAIL: java benchmark"
fi

#elif [ "$1" == "debug" ]; then
#  time java -agentlib:hprof=cpu=samples $EA -Djava.library.path=$SCRIPT_DIR/include/ -jar \
#      target/CobraVerifier-0.0.1-SNAPSHOT-jar-with-dependencies.jar count T T T T /tmp/cobra/log || fail "FAIL: java benchmark"
#fi

echo "DONE"
