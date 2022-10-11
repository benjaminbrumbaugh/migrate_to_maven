#!/usr/bin/env python
import argparse
import distutils
import math
import os.path
import pathlib
import re
import shutil
import subprocess
import sys
from re import Pattern
from tempfile import TemporaryDirectory
from zipfile import ZipFile

from zenlog import log

# You can reconfigure these before running #
MAVEN_PLUGIN: str = "org.apache.maven.plugins:maven-install-plugin:3.0.0-M1"  # Forces the version of the maven-install-plugin
MAVEN_FLAGS: str = ''  # You can pass Maven additional flags here like -s -v --whatever
MAVEN_JVM_FLAGS: str = '-DtrimStackTrace=false -DcreateChecksum=true -Dstyle.color=never'  # Flags that go to the JVM running Maven; -Dflag=value
LOCATION_OF_LOOSE_JAVA_FILES = './external'
####


# Probably don't need to touch these #
MAKE_SHELL_BLUE: str = "tput -T xterm-256color setaf 4;"  # Shell prefix that turns the output blue
GLOBAL_FOUND_METADATA: \
    dict[str:dict] = dict()  # Global dictionary of jar path (str) to metadata dictionary {metadata key, metadata value}
GLOBAL_LOOSE_JAVA_FILES: list[str] = []  # Global list of .java files that are not found inside jars
GLOBAL_JAVA_FILES_IN_JARS: list[str] = []  # Global list of .java and .class files found inside jars
COMMONALITY_THRESHOLD: float = 0.80  # Manually derived percent value; how often a path substring must appear in other path substrings to be considered common


####

# def length_then_alphabetical_comparator(x: str, y: str) -> int:
#     match x, y:
#         case None, None:
#             return 0
#         case None, _:
#             return 1
#         case _, None:
#             return -1
#
#     length_difference = len(x) - len(y)
#     if length_difference != 0:
#         return length_difference
#     return


def dedupe(duplicates: list) -> list:
    if not duplicates:
        return duplicates
    return list(dict.fromkeys(duplicates))


def scan_jar_for_java_files(path_to_jar_file: str):
    if not path_to_jar_file:
        return []
    with TemporaryDirectory() as tmp:
        ZipFile(path_to_jar_file).extractall(path=tmp)
        identify_all_java_files(tmp, True)


def identify_all_java_files(path: str, from_jar: bool = False):
    if not path:
        return []
    if os.path.isdir(path):
        for root, _, files in os.walk(path, followlinks=True):
            for file in files:
                identify_all_java_files(os.path.join(root, file), from_jar)
    suffix: str = pathlib.Path(path.lower()).suffix
    match suffix:
        case '.jar':
            log.debug(f"Is a jar and needs to be extracted and inspected: {path}")
            scan_jar_for_java_files(path)
        case '.java':
            log.debug(f"Adding .java file: {path}")
            add_to_global_java_files([path], from_jar)
        case '.class':
            if from_jar:
                log.debug(f"Adding .class file: {path}")
                add_to_global_java_files([path], from_jar)
            else:
                log.debug(f"Skipping loose class file: {path}")
        case _:
            log.debug(f"Skipped non-java file: {path}")


def add_to_global_java_files(java_files: list[str], from_jar: bool = False):
    if not java_files:
        return
    if not from_jar:
        global GLOBAL_LOOSE_JAVA_FILES
        GLOBAL_LOOSE_JAVA_FILES.extend(java_files)
        GLOBAL_LOOSE_JAVA_FILES = dedupe(GLOBAL_LOOSE_JAVA_FILES)
    else:
        global GLOBAL_JAVA_FILES_IN_JARS
        GLOBAL_JAVA_FILES_IN_JARS.extend(java_files)
        GLOBAL_JAVA_FILES_IN_JARS = dedupe(GLOBAL_JAVA_FILES_IN_JARS)


def identify_all_jars(paths: list[str]) -> list[str]:
    """
    Finds all jars in {paths}. If it's a directory instead of a jar file, it walks it recursively.
    """
    jar_list: list[str] = []
    for path in paths:
        if os.path.isdir(path):
            for root, _, files in os.walk(path, followlinks=True):
                for file in files:
                    identify_all_java_files(os.path.join(root, file))
                    if file.lower().endswith('.jar'):
                        jar_list.append(os.path.join(root, file))
        else:
            if path.lower().endswith('.jar'):
                jar_list.append(path)
    deduped_jars = list(dict.fromkeys(jar_list))
    if deduped_jars:
        log.info(f"Found {len(deduped_jars)} jars to install: {deduped_jars}")
    else:
        log.warning(f"Found no jars within given paths: {paths}")
    return deduped_jars


def parse_args() -> list[str]:
    """
    Parses the program input arguments and returns the provided jar paths.
    """
    parser = argparse.ArgumentParser(
        description='Recursively traverses a list of directories and jars and installs them into Apache Maven.')
    parser.add_argument('paths', nargs='+', type=str, help='<Required> Must provide jar or dir paths.')
    args = parser.parse_args()
    log.debug(args.paths)
    return args.paths


def expand_command_with_arguments(command: str, jar: str, arguments: dict):
    """
    Given a command string and a jar path, replaces <jar> and other <placeholders> in the command string.
    """
    expanded: str = command.replace("<jar>", jar)
    if arguments and jar in arguments:
        for metadata_key, metadata_value in arguments[jar].items():
            expanded = expanded.replace(f"<{metadata_key}>", metadata_value)
    return expanded


def try_maven_install(jars: list[str], command: str, arguments: dict) -> list[str]:
    """
    Runs the maven install command on each jar in {jars}, with variables subbed in for <placeholders>.
    """
    successes: list[str] = []
    for index, jar in enumerate(jars):
        expanded_command = expand_command_with_arguments(command, jar, arguments)
        progress_prefix = f"{index + 1} of {len(jars)}:"
        log.debug(f"{progress_prefix} Trying to maven install jar: {jar}")
        try:
            log.debug(f"Running command: {expanded_command}")
            response_code = os.system(expanded_command)
            if response_code == 0:
                successes.append(jar)
                log.debug(f"{progress_prefix} Installed {jar} successfully!")
            else:
                log.debug(f"{progress_prefix} Could not maven install jar {jar}, error code: {response_code}")
        except BaseException as error:
            log.warning(error)
    log.info(f"Found {len(successes)} of {len(jars)} maven-ready jars and installed them: {successes}")
    return successes


def jar_strategy_try_maven_install(jars: list[str]) -> list[str]:
    """
    A strategy that uses the basic form of the maven install command with no metadata parameters.
    This will successfully install jars that are already populated with maven's pom.xml.
    """
    command = f"{MAKE_SHELL_BLUE} mvn {MAVEN_FLAGS} {MAVEN_PLUGIN}:install-file -Dfile=<jar> {MAVEN_JVM_FLAGS}"
    return try_maven_install(jars, command, {})


def metadata_strategy_maven_install_from_metadata(_) -> list[str]:
    """
    A strategy that uses the fully qualified form of the maven install command with the metadata parameters provided.
    """
    command = f"{MAKE_SHELL_BLUE} mvn {MAVEN_FLAGS} {MAVEN_PLUGIN}:install-file -Dfile=<jar> -DgroupId=<group-id> -DartifactId=<artifact-id> -Dversion=<version> -Dpackaging=jar {MAVEN_JVM_FLAGS}"
    (complete_metadata, _) = find_metadata_complete_jars()
    return try_maven_install([*complete_metadata], command, GLOBAL_FOUND_METADATA)


def test_metadata_against_type_criteria(metadata_key: str, metadata_value: str):
    """
    Required criteria that a piece of metadata must pass in order to even be considered a reasonable guess.
    """
    if metadata_value is None:
        return False
    DOT_DELIMINATED = re.compile("^.+\\..+$")
    CONTAINS_NUMERIC_VALUES = re.compile("^.*[0-9]+.*$")
    CONTAINS_ALPHA_VALUES = re.compile("^.*[a-z|A-Z]+.*$")
    CONTAINS_NO_SPACES = re.compile("^\s*\S+\s*$")
    metadata_type_criteria: {str, list[Pattern]} = {
        "name": [CONTAINS_ALPHA_VALUES],
        "group-id": [CONTAINS_ALPHA_VALUES, CONTAINS_NO_SPACES],
        "artifact-id": [CONTAINS_ALPHA_VALUES, CONTAINS_NO_SPACES],
        "version": [DOT_DELIMINATED, CONTAINS_NUMERIC_VALUES, CONTAINS_NO_SPACES],
    }
    for regex in metadata_type_criteria[metadata_key]:
        if not regex.match(metadata_value):
            return False
    return True


def parse_manifest(manifest: str) -> dict:
    """
    Parses the {manifest} for metadata with a list of search criteria.
    """
    if not manifest:
        return {}
    # Precedence is right to left, so worst guess to best guess
    metadata_key_to_manifest_search_strings_map: {str, list[str]} = {
        "name": ["Extension-Name:", "Implementation-Title:", "Bundle-SymbolicName:", "Specification-Title:"],
        "group-id": ["Specification-Title:", "Implementation-Vendor-Id:", "Implementation-Title:"],
        "artifact-id": ["Specification-Title:", "Extension-Name:", "Implementation-Title:", "Bundle-SymbolicName:"],
        "version": ["Bundle-Version:", "Specification-Version:", "Implementation-Version:"],
    }
    found_metadata: {str, str} = dict()
    for metadata_key, manifest_strings in metadata_key_to_manifest_search_strings_map.items():
        for manifest_string in manifest_strings:
            for line in manifest.splitlines(keepends=False):
                if line:
                    match = re.search(manifest_string, line, flags=re.IGNORECASE)
                    if match:
                        match_cleaned = match.string[len(manifest_string):].strip()
                        if match_cleaned is not None:
                            found_metadata[metadata_key] = match_cleaned
                            log.debug(f"{metadata_key}: {found_metadata[metadata_key]}")
    return found_metadata


def merge_metadata(base_metadata: dict[str:dict], metadata_to_merge_in: dict[str:dict], overwrite: bool = True) -> dict[
                                                                                                                   str:dict]:
    """
    Merges metadata from {metadata_to_merge_in} into {base_metadata}. Updates value in {base_metadata} if the key already exists.
    {overwrite} True (default) updates entry if already defined.
    {overwrite} False skips entry if already defined.
    """
    if not base_metadata:
        return metadata_to_merge_in
    if not metadata_to_merge_in:
        return base_metadata
    for key, value in metadata_to_merge_in.items():
        if value is not None:
            if overwrite or key not in base_metadata:
                base_metadata[key] = value
    return base_metadata


def add_to_global_metadata(jar: str, metadata: dict[str:str], overwrite: bool = True):
    """
    Adds only valid {metadata} to the global metadata under {jar}. Merges in {metadata} if {jar} metadata already exists.
    {overwrite} True (default) updates entry if already defined.
    {overwrite} False skips entry if already defined.
    """
    if jar and metadata:
        valid_metadata: dict[str:str] = {}
        for metadata_key, metadata_value in metadata.items():
            if test_metadata_against_type_criteria(metadata_key, metadata_value):
                valid_metadata[metadata_key] = metadata_value
        global GLOBAL_FOUND_METADATA
        if jar in GLOBAL_FOUND_METADATA:
            merged_metadata = merge_metadata(GLOBAL_FOUND_METADATA[jar], valid_metadata, overwrite)
            GLOBAL_FOUND_METADATA[jar] = merged_metadata
        else:
            GLOBAL_FOUND_METADATA[jar] = valid_metadata


def metadata_strategy_parse_manifest(jars: list[str]) -> list[str]:
    """
    A strategy that tries to parse the MANIFEST.MF file inside the jar for metadata.
    """
    for index, jar in enumerate(jars):
        progress_prefix = f"{index + 1} of {len(jars) + 1}:"
        log.debug(f"{progress_prefix} Trying to parse manifest in jar: {jar}")
        manifest = ""
        try:
            manifest = subprocess.check_output(
                [f"unzip -q -c {jar} META-INF/MANIFEST.MF"], stderr=subprocess.STDOUT, shell=True).decode(
                sys.stdout.encoding)
            log.debug(f"{progress_prefix} Manifest file:\n{manifest}")
        except BaseException as error:
            log.warning(error)
        found_metadata = parse_manifest(manifest)
        log.debug(f"{progress_prefix} Found metadata:\n {found_metadata}")
        add_to_global_metadata(jar, found_metadata, overwrite=False)
    return []


def remove_path_suffix(substring: str) -> str:
    """
    Given 'Volume_Viewer.class', returns 'Volume_Viewer'
    """
    dollar_dot_class = re.compile("(\$)?[0-9]*\\.class$", re.IGNORECASE)
    if not substring:
        return ''
    cleaned_string = re.sub(dollar_dot_class, '', substring)
    return cleaned_string


def find_longest_common_substring(all_substrings: list) -> str:
    """
    Given a list of strings, checks each of them for how many times it occurs as a substring of the others.
    Then, sorting by the number of occurrences high-to-low, it iterates down the list looking for the longest substring.
    However, this alone would just yield the longest string in {all_substrings}, without much regard for the occurrences.
    The problem comes from the fact that we're trying to search by two criteria, the longest string with the most occurrences,
    and these are independent variables, so we'll need a heuristic approach. To solve this we'll take all substrings with
    an occurrence value in the top X percent given by {COMMONALITY_THRESHOLD}.
    """
    if not all_substrings:
        return ''
    occurrences: dict[str, int] = dict()
    for substring in all_substrings:
        for compare_string in all_substrings:
            if substring in compare_string:
                if substring in occurrences:
                    occurrences[substring] += 1
                else:
                    occurrences[substring] = 1
    if occurrences:
        sorted(occurrences.items(), key=lambda key: key[1], reverse=True)
        maximum_occurrence = list(occurrences.values())[0]
        high_occurrence_strings: dict[str, int] = dict()
        for occurrence in occurrences:
            if occurrences[occurrence] >= math.floor(maximum_occurrence * COMMONALITY_THRESHOLD):
                high_occurrence_strings[occurrence] = occurrences[occurrence]
        return max(high_occurrence_strings.keys())
    return ''


def remove_duplicates(ordered_list: list[any]) -> list[any]:
    """
    Preserves order but removes duplicates from {ordered_list}
    """
    return list(dict.fromkeys(ordered_list))


def deliminator_indices(substring: str) -> list[int]:
    """
    Returns the indices of the delimiters $, /, \
    Given org/micromanager/imageflipper$12.class returns [3, 17, 30]
    """
    if not substring:
        return []
    indices = []
    matches = re.finditer(r'\$|/|\\', substring)
    for match in matches:
        indices.append(match.span()[0])
    return indices


def deliminators_to_dots(deliminated_string: str) -> str:
    """
    Given org/micromanager/imageflipper$12.class returns org.micromanager.imageflipper.12.class
    """
    if not deliminated_string:
        return ''
    for deliminator_index in deliminator_indices(deliminated_string):
        deliminated_string = deliminated_string[:deliminator_index] + '.' + deliminators_to_dots(
            deliminated_string[deliminator_index + 1:])
    return deliminated_string


def find_most_common_substring(path_strings: list[str]) -> str:
    all_substrings = []
    ends_in_dot_class = re.compile("^.+\\.class$", re.IGNORECASE)
    for path_string in path_strings:
        if not path_string or not re.match(ends_in_dot_class, path_string):
            continue
        delimiters: list[int] = deliminator_indices(path_string)
        delimiters.append(len(path_string))
        for substring_end_index in delimiters:
            substring = path_string[:substring_end_index]
            if substring and delimiters:
                cleaned_substring = remove_path_suffix(substring)
                all_substrings.append(cleaned_substring)
    if all_substrings:
        deduped = remove_duplicates(all_substrings)
        return find_longest_common_substring(deduped)
    return ''


def metadata_strategy_infer_from_paths(jars: list[str]) -> list[str]:
    for index, jar in enumerate(jars):
        progress_prefix = f"{index + 1} of {len(jars) + 1}:"
        jar_file_tree = ''
        try:
            jar_file_tree = subprocess.check_output(
                [f"unzip -q -l {jar} | awk '{{print $4}}'"],
                stderr=subprocess.STDOUT, shell=True).decode(sys.stdout.encoding)
            log.debug(f"{progress_prefix} jar file tree:\n{jar_file_tree}")
        except BaseException as error:
            log.warning(error)
        jar_file_tree_list = jar_file_tree.splitlines()
        common_substring = find_most_common_substring(jar_file_tree_list)
        log.debug(f"For {jar} found common path substring: {common_substring}")
        group_id: str = deliminators_to_dots(common_substring)
        if group_id:
            metadata_to_add: dict[str:str] = {'group-id': group_id}
            if '.' in group_id:
                metadata_to_add['artifact-id'] = group_id[group_id.rfind('.') + 1:]
            else:
                metadata_to_add['artifact-id'] = group_id
            add_to_global_metadata(jar, metadata_to_add, overwrite=False)
    return []


def fill_metadata(jars: list[str], metadata_key: str, metadata_value: str = None):
    """
    Fills empty values in the global metadata for all {jars} with a valid {metadata_key: metadata_value}.
    If {metadata_value} is None, the jar's filename will be used instead.
    """
    for jar in jars:
        insert_value: str = metadata_value
        if insert_value is None:
            insert_value = os.path.basename(os.path.normpath(jar))
        if jar not in GLOBAL_FOUND_METADATA:
            GLOBAL_FOUND_METADATA[jar] = {metadata_key: insert_value}
        else:
            if metadata_key not in GLOBAL_FOUND_METADATA[jar]:
                add_to_global_metadata(jar, {metadata_key: insert_value}, overwrite=False)


def metadata_strategy_fill_dummy_version(jars: list[str]) -> []:
    fill_metadata(jars, 'version', '1.0')


def metadata_strategy_fill_dummy_artifact_name_from_jar_name(jars: list[str]) -> []:
    fill_metadata(jars, 'name')


def metadata_strategy_fill_dummy_artifact_id_from_jar_name(jars: list[str]) -> []:
    fill_metadata(jars, 'artifact-id')


def metadata_strategy_fill_dummy_group_id_from_jar_name(jars: list[str]) -> []:
    fill_metadata(jars, 'group-id')


def metadata_strategy_fill_dummy_values(jars: list[str]) -> []:
    metadata_strategy_fill_dummy_version(jars)
    metadata_strategy_fill_dummy_artifact_name_from_jar_name(jars)
    metadata_strategy_fill_dummy_artifact_id_from_jar_name(jars)
    metadata_strategy_fill_dummy_group_id_from_jar_name(jars)


def remove_all_from_list(a_list: list[str], to_remove: list[str]):
    if to_remove:
        return [i for i in a_list if i not in to_remove]
    else:
        return a_list.copy()


def run_strategy(pending_installs: list[str], strategy_method: any, step: int) -> list[str]:
    log.info(
        f"Strategy #{step}: Attempting to resolve {len(pending_installs)} jars using {strategy_method.__name__}: {pending_installs}")
    successful_installs = strategy_method(pending_installs)
    remaining_installs = remove_all_from_list(pending_installs.copy(), successful_installs)
    return remaining_installs


def run_jar_strategies(jars: list[str], strategy_list: list[any]) -> list[any]:
    remaining = jars.copy()
    for step, strategy in enumerate(strategy_list):
        remaining = run_strategy(remaining, strategy, step + 1)
        (full_metadata, partial_metadata) = find_metadata_complete_jars()
        log.debug(f"Full match global metadata map ({len(full_metadata.keys())}): {full_metadata}")
        log.debug(f"Partial match global metadata map ({len(partial_metadata.keys())}): {partial_metadata}")
        completed: int = len(jars) - len(remaining)
        percent_completed: int = int(round(completed / len(jars), 2) * 100)
        log.info(
            f'Overall progress is {percent_completed}% completed ({completed}/{len(jars)}); {len(remaining)} jars remain.')
    return remaining


def find_metadata_complete_jars() -> tuple[dict[str:dict], dict[str:dict]]:
    complete_metadata = {}
    incomplete_metadata = {}
    for jar, metadata in GLOBAL_FOUND_METADATA.items():
        if metadata and len(metadata) == 4:
            complete_metadata[jar] = metadata
        else:
            incomplete_metadata[jar] = metadata
    return complete_metadata, incomplete_metadata


def with_src_main(file_paths: list[str]) -> list[str]:
    if not file_paths:
        return []
    src_main_path = os.path.join('src', 'main')
    from_package = []
    for file_path in file_paths:
        if file_path:
            index = file_path.find(src_main_path)
            if index != -1:
                from_package.append(file_path)
    return from_package


def without_compiled_inner_classes(file_paths: list[str]) -> list[str]:
    non_inner_classes = []
    for file_path in file_paths:
        if file_path and '$' not in os.path.basename(file_path):
            non_inner_classes.append(file_path)
    return non_inner_classes


def without_file_extensions(file_paths: list[str]) -> list[str]:
    extensionless_paths = []
    for file_path in file_paths:
        if file_path:
            (extensionless_file_path, _) = os.path.splitext(file_path)
            extensionless_paths.append(extensionless_file_path)
    return extensionless_paths


def from_root_to_src_dir(paths: list[str]) -> list[str]:
    src_paths: list[str] = []
    for full_path in paths:
        path_from_root_to_component, path_component = os.path.split(full_path)
        while path_from_root_to_component:
            if path_component == 'src':
                src_paths.append(os.path.join(path_from_root_to_component, path_component))
                break
            path_from_root_to_component, path_component = os.path.split(path_from_root_to_component)
    return src_paths


def compare_last_url_components(string: str, compare_to: str, max_number_of_components: int = 3) -> bool:
    match string, compare_to:
        case None, None:
            return True
        case None, _:
            return False
        case _, None:
            return False
        case [], []:
            return True
    if max_number_of_components <= 0:
        return True
    (dir_path, filename) = os.path.split(string)
    (compare_dir_path, compare_filename) = os.path.split(compare_to)
    if filename == compare_filename:
        return compare_last_url_components(filename, compare_filename, max_number_of_components - 1)
    return False


def identify_unique_loose_java_files() -> list[str]:
    loose_java_files = without_file_extensions(GLOBAL_LOOSE_JAVA_FILES)
    jar_based_java_files = without_file_extensions(GLOBAL_JAVA_FILES_IN_JARS)
    jar_based_java_files = without_compiled_inner_classes(jar_based_java_files)
    unique_java_files: list[str] = []
    for index, loose_file in enumerate(loose_java_files):
        if any(compare_last_url_components(loose_file, jar_based_java_file) for jar_based_java_file in
               jar_based_java_files):
            log.debug(f"Found .java file with no representation in any of the jars: {loose_file}")
            # We'll cheat here and grab the full path with the .java extension from the global variable at the same index
            unique_java_files.append(GLOBAL_LOOSE_JAVA_FILES[index])
        else:
            log.debug(f"Found match for loose .java file: {loose_file}")
    return dedupe(unique_java_files)


def copy_files_to_external_dir(paths: list[str]):
    full_path = os.path.abspath(LOCATION_OF_LOOSE_JAVA_FILES)
    for file in paths:
        if file:
            log.debug(f"Copying file from {file} to {full_path}")
            shutil.copytree(file, LOCATION_OF_LOOSE_JAVA_FILES, dirs_exist_ok=True)


def jar_status_report(incomplete_jars: list[str]) -> int:
    if not incomplete_jars:
        return 0
    for index, incomplete_jar in enumerate(incomplete_jars):
        log.warn(f"{index + 1}/{len(incomplete_jars)}: Was unable to install jar {incomplete_jar}! This will need to be manually installed.")
    return len(incomplete_jars)


def java_file_status_report(incomplete_java_files: list[str]) -> int:
    if not incomplete_java_files:
        return 0
    for index, incomplete_java_file in enumerate(incomplete_java_files):
        log.warn(f"{index + 1}/{len(incomplete_java_files)}: No src directory found in {incomplete_java_file}! This java file was not automatically copied.")
    return len(incomplete_java_files)


if __name__ == '__main__':
    search_paths = parse_args()
    found_jars = identify_all_jars(search_paths)
    if not found_jars:
        log.fatal(f"Couldn't find any jars in {search_paths}!")
        exit(-1)
    strategies = [jar_strategy_try_maven_install,
                  metadata_strategy_infer_from_paths,
                  metadata_strategy_parse_manifest,
                  metadata_strategy_fill_dummy_values,
                  metadata_strategy_maven_install_from_metadata,
                  ]
    jars_skipped: list[str] = run_jar_strategies(found_jars, strategies)
    log.debug(f"Found {len(GLOBAL_LOOSE_JAVA_FILES)} loose java files: {GLOBAL_LOOSE_JAVA_FILES}")
    log.debug(f"Found {len(GLOBAL_JAVA_FILES_IN_JARS)} java files packed in jars: {GLOBAL_JAVA_FILES_IN_JARS}")
    loose_java_file_paths: list[str] = identify_unique_loose_java_files()
    log.info(f"Found {len(loose_java_file_paths)} java files not included inside jars: {loose_java_file_paths}")
    java_file_paths_with_src_dir: list[str] = with_src_main(loose_java_file_paths)
    java_files_skipped: list[str] = list(set(loose_java_file_paths).difference(java_file_paths_with_src_dir))
    dirs_to_copy: list[str] = dedupe(from_root_to_src_dir(java_file_paths_with_src_dir))
    log.info(f"Found {len(dirs_to_copy)} src directories to copy to install found loose java files: {dirs_to_copy}")
    copy_files_to_external_dir(dirs_to_copy)
    jar_issues: int = jar_status_report(jars_skipped)
    java_file_issues: int = java_file_status_report(java_files_skipped)
    issues: int = jar_issues + java_file_issues
    log.info(f"{len(found_jars) - jar_issues}/{len(found_jars)} jars and {len(loose_java_file_paths) - java_file_issues}/{len(loose_java_file_paths)} additional java files installed successfully.")
    exit(issues * -1)  # Will return 0 (successful) if all jars and java files were installed, otherwise (failure) a negative count of the issues identified
