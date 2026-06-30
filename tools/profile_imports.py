#!/usr/bin/env python3
"""
Import profiling tool for AWS Tag Manager CLI.
Analyzes import times and dependencies to identify optimization opportunities.
"""

import ast
import importlib.util
import json
import os
import subprocess
import sys
import time
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Set, Tuple

# ANSI color codes
GREEN = '\033[92m'
YELLOW = '\033[93m'
RED = '\033[91m'
BLUE = '\033[94m'
BOLD = '\033[1m'
RESET = '\033[0m'


class ImportProfiler:
    """Analyzes and profiles Python imports."""

    def __init__(self):
        self.import_times: Dict[str, float] = {}
        self.import_graph: Dict[str, Set[str]] = defaultdict(set)
        self.module_sizes: Dict[str, int] = {}

    def extract_imports_from_file(self, file_path: Path) -> List[str]:
        """Extract all import statements from a Python file."""
        imports = []

        try:
            with open(file_path, 'r') as f:
                tree = ast.parse(f.read())

            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        imports.append(alias.name)
                elif isinstance(node, ast.ImportFrom):
                    if node.module:
                        imports.append(node.module)

        except Exception as e:
            print(f"{YELLOW}Warning: Could not parse {file_path}: {e}{RESET}")

        return imports

    def build_import_graph(self, root_path: Path) -> None:
        """Build a graph of import dependencies."""
        print(f"{BLUE}Building import dependency graph...{RESET}")

        for py_file in root_path.rglob('*.py'):
            if '__pycache__' in str(py_file):
                continue

            module_name = self._path_to_module(py_file, root_path)
            imports = self.extract_imports_from_file(py_file)

            for imp in imports:
                # Only track project imports
                if imp.startswith('tag_manager_cli'):
                    self.import_graph[module_name].add(imp)

            # Track file size
            self.module_sizes[module_name] = py_file.stat().st_size

    def _path_to_module(self, file_path: Path, root_path: Path) -> str:
        """Convert file path to module name."""
        relative_path = file_path.relative_to(root_path.parent)
        module_parts = list(relative_path.parts[:-1]) + [relative_path.stem]
        return '.'.join(module_parts)

    def measure_import_time(self, module_name: str) -> float:
        """Measure the time to import a specific module."""
        # Create a subprocess to measure clean import time
        code = f"""
import time
start = time.perf_counter()
import {module_name}
elapsed = time.perf_counter() - start
print(elapsed)
"""

        try:
            result = subprocess.run(
                [sys.executable, '-c', code],
                capture_output=True,
                text=True,
                timeout=10,
                cwd=Path.cwd()
            )

            if result.returncode == 0 and result.stdout:
                return float(result.stdout.strip()) * 1000  # Convert to ms
        except Exception:
            pass

        return 0.0

    def profile_main_imports(self) -> Dict[str, float]:
        """Profile imports from main.py using importtime."""
        print(f"{BLUE}Profiling main.py imports...{RESET}")

        cmd = [sys.executable, '-X', 'importtime', '-m', 'tag_manager_cli.main', '--help']

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=30
            )

            if result.returncode == 0:
                return self._parse_importtime_output(result.stderr)
        except Exception as e:
            print(f"{RED}Error profiling imports: {e}{RESET}")

        return {}

    def _parse_importtime_output(self, output: str) -> Dict[str, float]:
        """Parse Python's -X importtime output."""
        import_times = {}
        cumulative_times = {}

        for line in output.split('\n'):
            if 'import time:' in line:
                parts = line.split('|')
                if len(parts) >= 2:
                    try:
                        # Extract self and cumulative times
                        times = parts[0].strip().split()
                        if len(times) >= 2:
                            self_time = int(times[0])
                            cumulative = int(times[1])
                            module_name = parts[1].strip()

                            # Convert microseconds to milliseconds
                            import_times[module_name] = self_time / 1000
                            cumulative_times[module_name] = cumulative / 1000
                    except (ValueError, IndexError):
                        continue

        return import_times

    def find_heavy_imports(self, threshold_ms: float = 10) -> List[Tuple[str, float]]:
        """Find imports that take longer than threshold."""
        heavy_imports = [
            (module, time_ms)
            for module, time_ms in self.import_times.items()
            if time_ms > threshold_ms
        ]
        return sorted(heavy_imports, key=lambda x: x[1], reverse=True)

    def analyze_import_chains(self) -> Dict[str, List[str]]:
        """Analyze import dependency chains."""
        chains = {}

        # Find modules with deep import chains
        for module in self.import_graph:
            chain = self._get_import_chain(module, set())
            if len(chain) > 3:  # Only show deep chains
                chains[module] = chain

        return chains

    def _get_import_chain(self, module: str, visited: Set[str], depth: int = 0) -> List[str]:
        """Recursively build import chain."""
        if module in visited or depth > 10:
            return []

        visited.add(module)
        chain = [module]

        for imported in self.import_graph.get(module, []):
            sub_chain = self._get_import_chain(imported, visited.copy(), depth + 1)
            if sub_chain:
                chain.extend(sub_chain)

        return chain

    def generate_report(self) -> None:
        """Generate comprehensive import analysis report."""
        print(f"\n{BOLD}=== Import Analysis Report ==={RESET}\n")

        # 1. Top-level import times
        import_times = self.profile_main_imports()
        if import_times:
            print(f"{BOLD}Top 20 Slowest Imports:{RESET}")
            print(f"{'Module':<50} {'Time (ms)':<15} {'Category'}")
            print("-" * 80)

            sorted_imports = sorted(
                import_times.items(),
                key=lambda x: x[1],
                reverse=True
            )[:20]

            for module, time_ms in sorted_imports:
                # Categorize imports
                if 'boto' in module:
                    category = f"{RED}AWS SDK{RESET}"
                elif 'sqlalchemy' in module or 'alembic' in module:
                    category = f"{YELLOW}Database{RESET}"
                elif 'rich' in module or 'click' in module or 'typer' in module:
                    category = f"{BLUE}CLI Framework{RESET}"
                elif 'tag_manager_cli' in module:
                    category = f"{GREEN}Project{RESET}"
                else:
                    category = "External"

                # Color code by time
                if time_ms > 50:
                    time_str = f"{RED}{time_ms:.1f}{RESET}"
                elif time_ms > 20:
                    time_str = f"{YELLOW}{time_ms:.1f}{RESET}"
                else:
                    time_str = f"{GREEN}{time_ms:.1f}{RESET}"

                print(f"{module:<50} {time_str:<25} {category}")

            # Summary statistics
            total_time = sum(import_times.values())
            print(f"\n{BOLD}Import Statistics:{RESET}")
            print(f"  Total import time: {total_time:.1f}ms")
            print(f"  Number of modules: {len(import_times)}")
            print(f"  Average per module: {total_time/len(import_times):.1f}ms")

        # 2. Heavy module analysis
        print(f"\n{BOLD}Heavy Modules (by file size):{RESET}")
        sorted_sizes = sorted(
            self.module_sizes.items(),
            key=lambda x: x[1],
            reverse=True
        )[:10]

        for module, size in sorted_sizes:
            size_kb = size / 1024
            if size_kb > 50:
                size_str = f"{RED}{size_kb:.1f}KB{RESET}"
            elif size_kb > 20:
                size_str = f"{YELLOW}{size_kb:.1f}KB{RESET}"
            else:
                size_str = f"{GREEN}{size_kb:.1f}KB{RESET}"
            print(f"  {module:<50} {size_str}")

        # 3. Import recommendations
        print(f"\n{BOLD}Optimization Recommendations:{RESET}\n")

        # Identify problematic imports
        problems = []

        # Check for heavy imports at module level
        if import_times:
            sorted_imports_for_problems = sorted(
                import_times.items(),
                key=lambda x: x[1],
                reverse=True
            )[:10]
        else:
            sorted_imports_for_problems = []

        for module, time_ms in sorted_imports_for_problems:
            if 'boto' in module and time_ms > 100:
                problems.append(
                    f"• {RED}boto3{RESET} takes {time_ms:.0f}ms to import\n"
                    f"  → Consider lazy loading: only import when AWS operations are needed"
                )
            elif 'sqlalchemy' in module and time_ms > 50:
                problems.append(
                    f"• {YELLOW}SQLAlchemy{RESET} takes {time_ms:.0f}ms to import\n"
                    f"  → Defer database initialization until first query"
                )
            elif 'tag_manager_cli.commands' in module:
                problems.append(
                    f"• Command module {BLUE}{module}{RESET} loaded eagerly\n"
                    f"  → Use dynamic imports based on selected command"
                )

        # Check for import chains
        chains = self.analyze_import_chains()
        if chains:
            deep_chains = [
                (module, len(chain))
                for module, chain in chains.items()
                if len(chain) > 5
            ][:3]

            for module, depth in deep_chains:
                problems.append(
                    f"• Deep import chain in {YELLOW}{module}{RESET} (depth: {depth})\n"
                    f"  → Consider breaking up module dependencies"
                )

        # Print recommendations
        if problems:
            for problem in problems[:5]:  # Top 5 issues
                print(problem)
        else:
            print(f"{GREEN}No major import issues detected!{RESET}")

        # 4. Quick wins
        print(f"\n{BOLD}Quick Wins for Performance:{RESET}")
        print(f"1. Lazy load boto3 - save ~{self._estimate_boto3_savings(import_times):.0f}ms")
        print(f"2. Defer database init - save ~{self._estimate_db_savings(import_times):.0f}ms")
        print(f"3. Dynamic command loading - save ~{self._estimate_command_savings(import_times):.0f}ms")
        print(f"4. Skip health checks for --help - save ~50-100ms")
        print(f"5. Lazy cache initialization - save ~50-100ms")

        estimated_total = (
            self._estimate_boto3_savings(import_times) +
            self._estimate_db_savings(import_times) +
            self._estimate_command_savings(import_times) +
            100  # Health checks + cache
        )
        print(f"\n{BOLD}Estimated total savings: {GREEN}{estimated_total:.0f}ms{RESET}")

    def _estimate_boto3_savings(self, import_times: Dict[str, float]) -> float:
        """Estimate savings from lazy loading boto3."""
        return sum(t for m, t in import_times.items() if 'boto' in m)

    def _estimate_db_savings(self, import_times: Dict[str, float]) -> float:
        """Estimate savings from lazy loading database."""
        return sum(t for m, t in import_times.items() if 'sqlalchemy' in m or 'alembic' in m)

    def _estimate_command_savings(self, import_times: Dict[str, float]) -> float:
        """Estimate savings from dynamic command loading."""
        return sum(t for m, t in import_times.items() if 'tag_manager_cli.commands' in m)

    def save_analysis(self, filename: str) -> None:
        """Save analysis results to JSON."""
        import_times = self.profile_main_imports()

        results = {
            'timestamp': time.strftime('%Y-%m-%d %H:%M:%S'),
            'import_times': import_times,
            'total_time_ms': sum(import_times.values()),
            'module_count': len(import_times),
            'heavy_imports': [
                {'module': m, 'time_ms': t}
                for m, t in sorted(import_times.items(), key=lambda x: x[1], reverse=True)[:20]
            ],
            'estimates': {
                'boto3_savings_ms': self._estimate_boto3_savings(import_times),
                'database_savings_ms': self._estimate_db_savings(import_times),
                'commands_savings_ms': self._estimate_command_savings(import_times),
                'total_potential_savings_ms': (
                    self._estimate_boto3_savings(import_times) +
                    self._estimate_db_savings(import_times) +
                    self._estimate_command_savings(import_times) +
                    100
                )
            }
        }

        with open(filename, 'w') as f:
            json.dump(results, f, indent=2)

        print(f"\n{GREEN}Analysis saved to {filename}{RESET}")


def main():
    """Main entry point."""
    import argparse

    parser = argparse.ArgumentParser(
        description='Profile and analyze imports for AWS Tag Manager CLI'
    )
    parser.add_argument('--save', '-s', type=str,
                      help='Save analysis to JSON file')
    parser.add_argument('--module', '-m', type=str,
                      help='Analyze specific module')
    parser.add_argument('--threshold', '-t', type=float, default=10.0,
                      help='Time threshold in ms for heavy imports (default: 10)')

    args = parser.parse_args()

    # Create profiler
    profiler = ImportProfiler()

    # Build import graph
    project_root = Path.cwd() / 'tag_manager_cli'
    if project_root.exists():
        profiler.build_import_graph(project_root)

    # Generate report
    profiler.generate_report()

    # Save if requested
    if args.save:
        profiler.save_analysis(args.save)
    else:
        # Auto-save with timestamp
        timestamp = time.strftime('%Y%m%d_%H%M%S')
        filename = f'import_analysis_{timestamp}.json'
        profiler.save_analysis(filename)


if __name__ == '__main__':
    main()