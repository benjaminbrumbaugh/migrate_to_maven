import argparse
import logging
import os.path
import re

# Configure these #
LOGGING_LEVEL = logging.DEBUG
MAVEN_PLUGIN = "org.apache.maven.plugins:maven-install-plugin:3.0.0-M1"
####

MAKE_SHELL_BLUE = "tput -T xterm-256color setaf 4;"
GREEN = '\033[0;32m'
RED = '\033[0;31m'
GRAY = '\x1b[38;20m'


def identify_all_jars(paths):
    jar_list: list[str] = []
    for path in paths:
        if os.path.isdir(path):
            for root, dirs, files in os.walk(path):
                for name in files:
                    if name.lower().endswith('.jar'):
                        jar_list.append(os.path.join(root, name))
        else:
            if re.search('jar$', path, flags=re.IGNORECASE):
                jar_list.append(path)
    deduped_jars = list(dict.fromkeys(jar_list))
    logging.info(f"Found jars to install: {deduped_jars}")
    return deduped_jars


def setup_logger():
    logger_format = "[%(filename)s:%(lineno)s - %(funcName)20s() ] %(message)s"
    logging.basicConfig(format=logger_format, level=LOGGING_LEVEL)
    logging.addLevelName(logging.INFO, "\033[0;32m%s\033[1;0m" % logging.getLevelName(logging.INFO))
    logging.addLevelName(logging.DEBUG, "\x1b[38;20m%s\033[1;0m" % logging.getLevelName(logging.DEBUG))
    logging.addLevelName(logging.WARNING, "\033[1;31m%s\033[1;0m" % logging.getLevelName(logging.WARNING))
    logging.addLevelName(logging.ERROR, "\033[1;41m%s\033[1;0m" % logging.getLevelName(logging.ERROR))


def parse_args():
    parser = argparse.ArgumentParser(
        description='Recursively traverses a list of directories and jars and installs them into Apache Maven.')
    parser.add_argument('paths', action="extend", nargs="+", type=str)
    args = parser.parse_args()
    logging.debug(args.paths)
    return args.paths


def metadata_strategy_try_maven(jars):
    successes: list[str] = []
    for jar in jars:
        try:
            outcome = os.system(f"{MAKE_SHELL_BLUE} mvn {MAVEN_PLUGIN}:install-file -Dfile={jar} -DcreateChecksum=true -Dstyle.color=never")
            if outcome == 0:
                successes.append(jar)
            else:
                logging.debug(outcome)
        except BaseException as error:
            logging.warning(error)
    logging.info(f"Found maven-ready jars and installed them: {successes}")
    return successes


if __name__ == '__main__':
    setup_logger()
    search_paths = parse_args()
    jar_paths = identify_all_jars(search_paths)
    successful_installs = metadata_strategy_try_maven(jar_paths)
