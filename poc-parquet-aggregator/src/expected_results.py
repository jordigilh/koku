"""Calculate expected aggregation results from nise static YAML."""

from datetime import datetime, timedelta
from typing import Dict, List
import yaml
import pandas as pd
from pathlib import Path

from .utils import get_logger


class ExpectedResultsCalculator:
    """Calculate expected aggregation results from nise static YAML configuration."""
    
    def __init__(self, yaml_path: str):
        """Initialize calculator with YAML path.
        
        Args:
            yaml_path: Path to nise static YAML file
        """
        self.yaml_path = Path(yaml_path)
        self.logger = get_logger("expected_results")
        self.config = self._load_yaml()
        
    def _load_yaml(self) -> Dict:
        """Load and parse YAML file.
        
        Returns:
            Parsed YAML configuration
        """
        with open(self.yaml_path, 'r') as f:
            config = yaml.safe_load(f)
        
        self.logger.info(f"Loaded YAML configuration: {self.yaml_path}")
        return config
    
    def calculate_expected_aggregations(self) -> pd.DataFrame:
        """Calculate expected daily aggregations from YAML configuration.
        
        Returns:
            DataFrame with expected results
        """
        results = []
        
        # Extract OCP generator config
        for generator in self.config.get('generators', []):
            if 'OCPGenerator' not in generator:
                continue
            
            ocp_gen = generator['OCPGenerator']
            start_date = datetime.strptime(ocp_gen['start_date'], '%Y-%m-%d').date()
            end_date = datetime.strptime(ocp_gen['end_date'], '%Y-%m-%d').date()
            
            # Generate results for each day in range
            current_date = start_date
            while current_date <= end_date:
                # Process each node
                for node in ocp_gen.get('nodes', []):
                    node_results = self._process_node(node, current_date)
                    results.extend(node_results)
                
                current_date += timedelta(days=1)
        
        df = pd.DataFrame(results)
        
        self.logger.info(
            f"Calculated expected results",
            total_rows=len(df),
            namespaces=df['namespace'].nunique() if not df.empty else 0,
            nodes=df['node'].nunique() if not df.empty else 0
        )
        
        return df
    
    def _process_node(self, node: Dict, date) -> List[Dict]:
        """Process a node configuration for a specific date.
        
        Args:
            node: Node configuration dictionary
            date: Date for aggregation
            
        Returns:
            List of expected result dictionaries
        """
        results = []
        
        node_name = node['node']['node_name']
        cpu_cores = node['node']['cpu_cores']
        memory_gig = node['node']['memory_gig']
        resource_id = node['node']['resource_id']
        
        # Node capacity (full day = 24 hours)
        node_capacity_cpu_core_hours = cpu_cores * 24.0
        node_capacity_memory_gigabyte_hours = memory_gig * 24.0
        
        # Process each namespace
        for namespace_name, namespace_config in node['node'].get('namespaces', {}).items():
            # Initialize aggregates for this namespace-node combination
            agg = {
                'usage_start': date,
                'usage_end': date,
                'namespace': namespace_name,
                'node': node_name,
                'resource_id': str(resource_id),
                'pod_usage_cpu_core_hours': 0.0,
                'pod_request_cpu_core_hours': 0.0,
                'pod_effective_usage_cpu_core_hours': 0.0,
                'pod_limit_cpu_core_hours': 0.0,
                'pod_usage_memory_gigabyte_hours': 0.0,
                'pod_request_memory_gigabyte_hours': 0.0,
                'pod_effective_usage_memory_gigabyte_hours': 0.0,
                'pod_limit_memory_gigabyte_hours': 0.0,
                'node_capacity_cpu_cores': cpu_cores,
                'node_capacity_cpu_core_hours': node_capacity_cpu_core_hours,
                'node_capacity_memory_gigabytes': memory_gig,
                'node_capacity_memory_gigabyte_hours': node_capacity_memory_gigabyte_hours,
                'data_source': 'Pod',
            }
            
            # Sum across all pods in this namespace
            for pod in namespace_config.get('pods', []):
                pod_dict = pod['pod']
                
                # Convert pod_seconds to hours
                pod_hours = pod_dict['pod_seconds'] / 3600.0
                
                # CPU metrics
                cpu_request = pod_dict.get('cpu_request', 0)
                cpu_limit = pod_dict.get('cpu_limit', 0)
                
                # For POC, assume usage = request (nise doesn't generate separate usage)
                cpu_usage = cpu_request
                
                agg['pod_usage_cpu_core_hours'] += cpu_usage * pod_hours
                agg['pod_request_cpu_core_hours'] += cpu_request * pod_hours
                agg['pod_limit_cpu_core_hours'] += cpu_limit * pod_hours
                
                # Effective usage = max(usage, request)
                cpu_effective = max(cpu_usage, cpu_request)
                agg['pod_effective_usage_cpu_core_hours'] += cpu_effective * pod_hours
                
                # Memory metrics
                mem_request_gig = pod_dict.get('mem_request_gig', 0)
                mem_limit_gig = pod_dict.get('mem_limit_gig', 0)
                
                # For POC, assume usage = request
                mem_usage_gig = mem_request_gig
                
                agg['pod_usage_memory_gigabyte_hours'] += mem_usage_gig * pod_hours
                agg['pod_request_memory_gigabyte_hours'] += mem_request_gig * pod_hours
                agg['pod_limit_memory_gigabyte_hours'] += mem_limit_gig * pod_hours
                
                # Effective usage = max(usage, request)
                mem_effective_gig = max(mem_usage_gig, mem_request_gig)
                agg['pod_effective_usage_memory_gigabyte_hours'] += mem_effective_gig * pod_hours
            
            # Only add if there are pods in this namespace
            if namespace_config.get('pods'):
                results.append(agg)
        
        return results
    
    def print_summary(self, df: pd.DataFrame):
        """Print a summary of expected results.
        
        Args:
            df: DataFrame with expected results
        """
        print("\n" + "=" * 80)
        print("EXPECTED RESULTS SUMMARY")
        print("=" * 80)
        print(f"Total Rows: {len(df)}")
        print(f"Date Range: {df['usage_start'].min()} to {df['usage_start'].max()}")
        print(f"Nodes: {df['node'].nunique()} ({', '.join(df['node'].unique())})")
        print(f"Namespaces: {df['namespace'].nunique()} ({', '.join(df['namespace'].unique())})")
        print()
        
        print("Total Metrics:")
        print(f"  Total CPU Request:    {df['pod_request_cpu_core_hours'].sum():,.2f} core-hours")
        print(f"  Total Memory Request: {df['pod_request_memory_gigabyte_hours'].sum():,.2f} GB-hours")
        print(f"  Total CPU Capacity:   {df['node_capacity_cpu_core_hours'].sum():,.2f} core-hours")
        print(f"  Total Memory Capacity:{df['node_capacity_memory_gigabyte_hours'].sum():,.2f} GB-hours")
        print()
        
        print("Per-Day Breakdown:")
        for date in sorted(df['usage_start'].unique()):
            day_df = df[df['usage_start'] == date]
            print(f"\n  {date}:")
            print(f"    Rows: {len(day_df)}")
            print(f"    CPU Request: {day_df['pod_request_cpu_core_hours'].sum():,.2f} core-hours")
            print(f"    Memory Request: {day_df['pod_request_memory_gigabyte_hours'].sum():,.2f} GB-hours")
        
        print("\n" + "=" * 80)
        print()
    
    def save_to_csv(self, df: pd.DataFrame, output_path: str):
        """Save expected results to CSV.
        
        Args:
            df: DataFrame with expected results
            output_path: Path to output CSV file
        """
        df.to_csv(output_path, index=False)
        self.logger.info(f"Saved expected results to: {output_path}")


def compare_results(expected_df: pd.DataFrame, actual_df: pd.DataFrame, tolerance: float = 0.0001) -> Dict:
    """Compare expected vs actual aggregation results.
    
    Args:
        expected_df: DataFrame with expected results
        actual_df: DataFrame with actual POC results
        tolerance: Acceptable relative difference (default 0.01%)
        
    Returns:
        Dictionary with comparison results
    """
    logger = get_logger("compare_results")
    
    # Merge on key columns
    merge_keys = ['usage_start', 'namespace', 'node']
    
    comparison = expected_df.merge(
        actual_df,
        on=merge_keys,
        how='outer',
        suffixes=('_expected', '_actual'),
        indicator=True
    )
    
    # Metrics to compare
    metrics = [
        'pod_usage_cpu_core_hours',
        'pod_request_cpu_core_hours',
        'pod_effective_usage_cpu_core_hours',
        'pod_limit_cpu_core_hours',
        'pod_usage_memory_gigabyte_hours',
        'pod_request_memory_gigabyte_hours',
        'pod_effective_usage_memory_gigabyte_hours',
        'pod_limit_memory_gigabyte_hours',
        'node_capacity_cpu_core_hours',
        'node_capacity_memory_gigabyte_hours',
    ]
    
    issues = []
    match_count = 0
    total_comparisons = 0
    
    # Check for missing rows
    missing_in_actual = comparison[comparison['_merge'] == 'left_only']
    missing_in_expected = comparison[comparison['_merge'] == 'right_only']
    
    if not missing_in_actual.empty:
        issues.append(f"Missing in actual: {len(missing_in_actual)} rows")
        for _, row in missing_in_actual.iterrows():
            issues.append(f"  - {row['usage_start']}, {row['namespace']}, {row['node']}")
    
    if not missing_in_expected.empty:
        issues.append(f"Extra in actual: {len(missing_in_expected)} rows")
        for _, row in missing_in_expected.iterrows():
            issues.append(f"  - {row['usage_start']}, {row['namespace']}, {row['node']}")
    
    # Compare values for matching rows
    both = comparison[comparison['_merge'] == 'both']
    
    for metric in metrics:
        expected_col = f"{metric}_expected"
        actual_col = f"{metric}_actual"
        
        if expected_col not in both.columns or actual_col not in both.columns:
            continue
        
        for _, row in both.iterrows():
            expected_val = row[expected_col]
            actual_val = row[actual_col]
            
            total_comparisons += 1
            
            # Handle None/NaN
            if pd.isna(expected_val) and pd.isna(actual_val):
                match_count += 1
                continue
            
            if pd.isna(expected_val) or pd.isna(actual_val):
                issues.append(
                    f"Null mismatch: {row['usage_start']}, {row['namespace']}, {row['node']}, "
                    f"{metric}: expected={expected_val}, actual={actual_val}"
                )
                continue
            
            # Calculate relative difference
            if expected_val != 0:
                rel_diff = abs(actual_val - expected_val) / abs(expected_val)
            else:
                rel_diff = abs(actual_val - expected_val)
            
            if rel_diff <= tolerance:
                match_count += 1
            else:
                issues.append(
                    f"Value mismatch: {row['usage_start']}, {row['namespace']}, {row['node']}, "
                    f"{metric}: expected={expected_val:.6f}, actual={actual_val:.6f}, "
                    f"diff={rel_diff:.2%}"
                )
    
    result = {
        'all_match': len(issues) == 0,
        'match_count': match_count,
        'total_comparisons': total_comparisons,
        'match_percentage': (match_count / total_comparisons * 100) if total_comparisons > 0 else 0,
        'issues': issues,
        'missing_in_actual_count': len(missing_in_actual),
        'extra_in_actual_count': len(missing_in_expected),
    }
    
    # Log summary
    if result['all_match']:
        logger.info("✅ ALL RESULTS MATCH EXPECTED VALUES!")
        logger.info(f"   {match_count}/{total_comparisons} comparisons passed")
    else:
        logger.error(f"❌ FOUND {len(issues)} DISCREPANCIES")
        logger.error(f"   {match_count}/{total_comparisons} comparisons passed ({result['match_percentage']:.1f}%)")
        for issue in issues[:10]:  # Show first 10
            logger.error(f"   {issue}")
        if len(issues) > 10:
            logger.error(f"   ... and {len(issues) - 10} more issues")
    
    return result


if __name__ == '__main__':
    """Run as standalone script to generate expected results."""
    import argparse
    
    parser = argparse.ArgumentParser(description="Calculate expected results from nise YAML")
    parser.add_argument('yaml_file', help='Path to nise static YAML file')
    parser.add_argument('--output', '-o', help='Output CSV file path')
    parser.add_argument('--print', '-p', action='store_true', help='Print summary to console')
    
    args = parser.parse_args()
    
    calculator = ExpectedResultsCalculator(args.yaml_file)
    df = calculator.calculate_expected_aggregations()
    
    if args.print:
        calculator.print_summary(df)
    
    if args.output:
        calculator.save_to_csv(df, args.output)
    else:
        # Default output
        output_path = Path(args.yaml_file).parent / 'expected_results.csv'
        calculator.save_to_csv(df, str(output_path))

