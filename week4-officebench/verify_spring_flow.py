"""Compile the scoped Spring flow class and JUnit test from existing local jars.

This avoids Maven's unavailable private HTTP repository; it never writes into
upstream teacher build directories or claims a full Spring application build.
"""
from pathlib import Path
import os
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
M2 = ROOT / '.m2/repository'
SOURCE = ROOT / 'rsi-skill-spring-boot/core-flow/src/main/java/com/horsecoder/common/whuTalent/core/flow/Run/code/FlowCodeRun.java'
TEST = ROOT / 'rsi-skill-spring-boot/core-flow/src/test/java/com/horsecoder/common/whuTalent/core/flow/Run/code/FlowCodeRunTest.java'
SMOKE = Path(__file__).resolve().parent / 'BridgeTransportSmoke.java'
OUT = Path(__file__).resolve().parent / 'java-verify'
OUT.mkdir(exist_ok=True)
parts = [
    M2/'com/fasterxml/jackson/core/jackson-databind/2.9.9.3/jackson-databind-2.9.9.3.jar',
    M2/'com/fasterxml/jackson/core/jackson-core/2.9.9/jackson-core-2.9.9.jar',
    M2/'com/fasterxml/jackson/core/jackson-annotations/2.9.0/jackson-annotations-2.9.0.jar',
    M2/'cc/eamon/open/flow-core/0.4.14/flow-core-0.4.14.jar',
    M2/'cc/eamon/open/flow-spring-boot-starter/0.4.14/flow-spring-boot-starter-0.4.14.jar',
    M2/'junit/junit/4.12/junit-4.12.jar',
    M2/'org/hamcrest/hamcrest-core/1.3/hamcrest-core-1.3.jar',
]
missing = [str(p) for p in parts if not p.is_file()]
if missing:
    raise SystemExit('Missing local jars: ' + ', '.join(missing))
classpath = os.pathsep.join(map(str, [OUT, *parts]))
subprocess.run(['javac', '-encoding', 'UTF-8', '-source', '8', '-target', '8', '-cp', classpath, '-d', str(OUT), str(SOURCE), str(TEST), str(SMOKE)], check=True)
subprocess.run(['java', '-cp', classpath, 'org.junit.runner.JUnitCore',
                'com.horsecoder.common.whuTalent.core.flow.Run.code.FlowCodeRunTest'], check=True)
if '--live' in sys.argv:
    subprocess.run(['java', '-cp', classpath,
                    'com.horsecoder.common.whuTalent.core.flow.Run.code.BridgeTransportSmoke'], check=True)
