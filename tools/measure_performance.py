#!/usr/bin/env python3
"""
Performance measurement tool for AWS Tag Manager CLI.
Measures startup time and execution performance for various commands.
"""

import json
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from statistics import mean, median, stdev
from typing import Dict, List, Optional, Tuple

# ANSI color codes for terminal output
GREEN = '\033[92m'
YELLOW = '\033[93m'
RED = '\033[91m'
BLUE = '\033[94m'
BOLD = '\033[1m'
RESET = '\033[0m'


class PerformanceMeasurement:
    """Measures CLI performance for various commands."""

    def __init__(self, iterations: int = 5):
        self.iterations = iterations
        self.results: Dict[str, List[float]] = {}

    def measure_command(self, command: List[str], description: str) -> Tuple[float, float]:
        """
        Measure execution time for a command.
        Returns average and standard deviation.
        """
        times = []
        print(f"{BLUE}Measuring: {description}{RESET}")

        for i in range(self.iterations):
            start_time = time.perf_counter()

            try:
                # Run command and capture output
                result = subprocess.run(
                    command,
                    capture_output=True,
                    text=True,
                    timeout=30
                )

                elapsed_time = time.perf_counter() - start_time
                times.append(elapsed_time * 1000)  # Convert to milliseconds

                # Show progress
                print(f"  Run {i+1}/{self.iterations}: {elapsed_time*1000:.1f}ms", end='\r')

            except subprocess.TimeoutExpired:
                print(f"{RED}  Timeout after 30 seconds{RESET}")
                return 0.0, 0.0
            except Exception as e:
                print(f"{RED}  Error: {e}{RESET}")
                return 0.0, 0.0

        avg_time = mean(times)
        std_dev = stdev(times) if len(times) > 1 else 0

        print(f"  {GREEN}Average: {avg_time:.1f}ms (±{std_dev:.1f}ms){RESET}")
        self.results[description] = times
        return avg_time, std_dev

    def run_benchmark_suite(self) -> Dict:
        """Run complete benchmark suite."""
        print(f"\n{BOLD}=== AWS Tag Manager CLI Performance Benchmark ==={RESET}")
        print(f"Running {self.iterations} iterations per command...\n")

        benchmark_results = {
            'timestamp': datetime.now().isoformat(),
            'iterations': self.iterations,
            'commands': {}
        }

        # Define test commands
        test_commands = [
            # Simple commands (should be fastest)
            ([sys.executable, '-m', 'tag_manager_cli.main', '--help'], 'Help command'),
            ([sys.executable, '-m', 'tag_manager_cli.main', '--version'], 'Version command'),

            # Diagnostic command
            ([sys.executable, '-m', 'tag_manager_cli.main', 'diagnostic', '--help'], 'Diagnostic help'),

            # Task commands (moderate complexity)
            ([sys.executable, '-m', 'tag_manager_cli.main', 'tasks', '--help'], 'Tasks help'),
            ([sys.executable, '-m', 'tag_manager_cli.main', 'tasks', 'list', '--no-check'], 'Tasks list (no check)'),

            # AWS commands (heaviest)
            ([sys.executable, '-m', 'tag_manager_cli.main', 'tags', '--help'], 'Tags help'),
            ([sys.executable, '-m', 'tag_manager_cli.main', 'discover', '--help'], 'Discover help'),

            # Database commands
            ([sys.executable, '-m', 'tag_manager_cli.main', 'database', '--help'], 'Database help'),

            # Update command
            ([sys.executable, '-m', 'tag_manager_cli.main', 'update', '--help'], 'Update help'),
        ]

        # Run benchmarks
        for command, description in test_commands:
            avg_time, std_dev = self.measure_command(command, description)
            benchmark_results['commands'][description] = {
                'command': ' '.join(command),
                'average_ms': round(avg_time, 2),
                'std_dev_ms': round(std_dev, 2),
                'median_ms': round(median(self.results[description]), 2) if description in self.results else 0,
                'min_ms': round(min(self.results[description]), 2) if description in self.results else 0,
                'max_ms': round(max(self.results[description]), 2) if description in self.results else 0,
                'raw_times': self.results.get(description, [])
            }

        return benchmark_results

    def compare_results(self, baseline_file: str, current_results: Dict) -> None:
        """Compare current results with baseline."""
        try:
            with open(baseline_file, 'r') as f:
                baseline = json.load(f)
        except FileNotFoundError:
            print(f"{YELLOW}No baseline file found at {baseline_file}{RESET}")
            return

        print(f"\n{BOLD}=== Performance Comparison ==={RESET}")
        print(f"Baseline from: {baseline['timestamp']}")
        print(f"Current from:  {current_results['timestamp']}\n")

        print(f"{'Command':<25} {'Baseline (ms)':<15} {'Current (ms)':<15} {'Change':<15} {'Status'}")
        print("-" * 85)

        for cmd_name, cmd_data in current_results['commands'].items():
            if cmd_name in baseline['commands']:
                baseline_time = baseline['commands'][cmd_name]['average_ms']
                current_time = cmd_data['average_ms']
                change = current_time - baseline_time
                change_pct = (change / baseline_time) * 100 if baseline_time > 0 else 0

                # Determine status color
                if change < -10:  # More than 10ms improvement
                    status = f"{GREEN}IMPROVED{RESET}"
                    change_str = f"{GREEN}{change:+.1f}ms ({change_pct:+.1f}%){RESET}"
                elif change > 10:  # More than 10ms regression
                    status = f"{RED}REGRESSION{RESET}"
                    change_str = f"{RED}{change:+.1f}ms ({change_pct:+.1f}%){RESET}"
                else:
                    status = f"{YELLOW}STABLE{RESET}"
                    change_str = f"{YELLOW}{change:+.1f}ms ({change_pct:+.1f}%){RESET}"

                print(f"{cmd_name:<25} {baseline_time:<15.1f} {current_time:<15.1f} {change_str:<25} {status}")

    def save_results(self, results: Dict, filename: str) -> None:
        """Save benchmark results to JSON file."""
        with open(filename, 'w') as f:
            json.dump(results, f, indent=2)
        print(f"\n{GREEN}Results saved to {filename}{RESET}")

    def print_summary(self, results: Dict) -> None:
        """Print performance summary."""
        print(f"\n{BOLD}=== Performance Summary ==={RESET}")

        # Group commands by category
        simple_commands = ['Help command', 'Version command']
        moderate_commands = ['Diagnostic help', 'Tasks help', 'Tasks list (no check)',
                           'Database help', 'Update help']
        heavy_commands = ['Tags help', 'Discover help']

        categories = [
            ('Simple Commands', simple_commands),
            ('Moderate Commands', moderate_commands),
            ('Heavy Commands', heavy_commands)
        ]

        for category_name, commands in categories:
            times = []
            for cmd in commands:
                if cmd in results['commands']:
                    times.append(results['commands'][cmd]['average_ms'])

            if times:
                avg = mean(times)
                print(f"\n{category_name}:")
                print(f"  Average: {avg:.1f}ms")
                print(f"  Range: {min(times):.1f}ms - {max(times):.1f}ms")

                # Performance rating
                if category_name == 'Simple Commands':
                    if avg < 100:
                        print(f"  Status: {GREEN}EXCELLENT (<100ms target){RESET}")
                    elif avg < 200:
                        print(f"  Status: {YELLOW}ACCEPTABLE{RESET}")
                    else:
                        print(f"  Status: {RED}NEEDS OPTIMIZATION (target: <100ms){RESET}")
                elif category_name == 'Heavy Commands':
                    if avg < 800:
                        print(f"  Status: {GREEN}EXCELLENT (<800ms target){RESET}")
                    elif avg < 1500:
                        print(f"  Status: {YELLOW}ACCEPTABLE{RESET}")
                    else:
                        print(f"  Status: {RED}NEEDS OPTIMIZATION (target: <800ms){RESET}")


def main():
    """Main entry point."""
    import argparse

    parser = argparse.ArgumentParser(description='Measure AWS Tag Manager CLI performance')
    parser.add_argument('--iterations', '-i', type=int, default=5,
                      help='Number of iterations per command (default: 5)')
    parser.add_argument('--save', '-s', type=str,
                      help='Save results to JSON file')
    parser.add_argument('--baseline', '-b', type=str,
                      help='Compare with baseline JSON file')
    parser.add_argument('--quick', action='store_true',
                      help='Quick mode - only test simple commands')

    args = parser.parse_args()

    # Create measurement instance
    pm = PerformanceMeasurement(iterations=args.iterations)

    # Run benchmarks
    results = pm.run_benchmark_suite()

    # Print summary
    pm.print_summary(results)

    # Compare with baseline if provided
    if args.baseline:
        pm.compare_results(args.baseline, results)

    # Save results if requested
    if args.save:
        pm.save_results(results, args.save)
    else:
        # Auto-save with timestamp
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        filename = f'performance_{timestamp}.json'
        pm.save_results(results, filename)

    # Check if optimization is needed
    simple_avg = mean([
        results['commands'][cmd]['average_ms']
        for cmd in ['Help command', 'Version command']
        if cmd in results['commands']
    ])

    if simple_avg > 200:
        print(f"\n{RED}{BOLD}⚠ Performance optimization needed!{RESET}")
        print(f"Simple commands averaging {simple_avg:.0f}ms (target: <100ms)")
        print("See PERFORMANCE_OPTIMIZATION.md for improvement strategies.")


if __name__ == '__main__':
    main()