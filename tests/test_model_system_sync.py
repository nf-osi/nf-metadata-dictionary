#!/usr/bin/env python3
"""
Simple test for the model system sync functionality.
"""

import os
import sys
import tempfile
import yaml
from pathlib import Path

# Add utils to path to import the sync script
utils_path = os.path.join(os.path.dirname(__file__), '..', 'utils')
sys.path.insert(0, utils_path)

try:
    import sync_model_systems
except ImportError:
    print(f"Could not import sync_model_systems from {utils_path}")
    sys.exit(1)


def test_format_enum_entry():
    """Test the format_enum_entry function."""
    
    # Test cell line entry without separate description (should not include description)
    cell_line = {
        'resourceName': 'Test Cell Line',
        'rrid': 'CVCL_0001',
        'resourceType': 'cell line'
    }
    
    result = sync_model_systems.format_enum_entry(cell_line)
    expected = {
        'Test Cell Line': {
            'source': 'https://web.expasy.org/cellosaurus/CVCL_0001'
        }
    }
    
    assert result == expected, f"Expected {expected}, got {result}"
    
    # Test cell line entry with different description (should include description)
    cell_line_with_desc = {
        'resourceName': 'Test Cell Line',
        'rrid': 'CVCL_0001',
        'resourceType': 'cell line',
        'description': 'This is a different description'
    }
    
    result = sync_model_systems.format_enum_entry(cell_line_with_desc)
    expected = {
        'Test Cell Line': {
            'description': 'This is a different description',
            'source': 'https://web.expasy.org/cellosaurus/CVCL_0001'
        }
    }
    
    assert result == expected, f"Expected {expected}, got {result}"
    
    # Test animal model entry without separate description
    animal_model = {
        'resourceName': 'Test Mouse Model',
        'rrid': 'MGI:0001',
        'resourceType': 'animal model'
    }
    
    result = sync_model_systems.format_enum_entry(animal_model)
    expected = {
        'Test Mouse Model': {
            'source': 'http://www.informatics.jax.org/accession/MGI:0001'
        }
    }
    
    assert result == expected, f"Expected {expected}, got {result}"
    
    print("✓ format_enum_entry tests passed")


def test_update_enum_file():
    """Test the update_enum_file function."""
    
    with tempfile.TemporaryDirectory() as temp_dir:
        test_file = os.path.join(temp_dir, 'test_enum.yaml')
        
        # Create test entries
        entries = [
            {'Test Entry 1': {'description': 'Description 1', 'source': 'source1'}},
            {'Test Entry 2': {'description': 'Description 2'}}
        ]
        
        # Update the file
        sync_model_systems.update_enum_file(test_file, 'TestEnum', entries)
        
        # Read and verify the file
        with open(test_file, 'r') as f:
            data = yaml.safe_load(f)
        
        assert 'enums' in data
        assert 'TestEnum' in data['enums']
        assert 'permissible_values' in data['enums']['TestEnum']
        assert len(data['enums']['TestEnum']['permissible_values']) == 2
        assert 'Test Entry 1' in data['enums']['TestEnum']['permissible_values']
        assert 'Test Entry 2' in data['enums']['TestEnum']['permissible_values']
        
        print("✓ update_enum_file tests passed")


def test_existing_files_format():
    """Test that existing enum files are valid YAML and have expected structure."""
    
    repo_root = Path(__file__).parent.parent
    
    # Test AnimalModel.yaml
    animal_model_file = repo_root / 'modules' / 'Sample' / 'AnimalModel.yaml'
    assert animal_model_file.exists(), f"AnimalModel.yaml not found at {animal_model_file}"
    
    with open(animal_model_file, 'r') as f:
        data = yaml.safe_load(f)
    
    assert 'enums' in data
    assert 'AnimalModel' in data['enums']
    assert 'permissible_values' in data['enums']['AnimalModel']
    assert len(data['enums']['AnimalModel']['permissible_values']) > 0
    
    # Test CellLineModel.yaml
    cell_line_file = repo_root / 'modules' / 'Sample' / 'CellLineModel.yaml'
    assert cell_line_file.exists(), f"CellLineModel.yaml not found at {cell_line_file}"
    
    with open(cell_line_file, 'r') as f:
        data = yaml.safe_load(f)
    
    assert 'enums' in data
    assert 'CellLineModel' in data['enums']
    assert 'permissible_values' in data['enums']['CellLineModel']
    assert len(data['enums']['CellLineModel']['permissible_values']) > 0
    
    print("✓ existing files format tests passed")


def main():
    """Run all tests."""
    try:
        test_format_enum_entry()
        test_update_enum_file()
        test_existing_files_format()
        print("\n🎉 All tests passed!")
        return 0
    except Exception as e:
        print(f"\n❌ Test failed: {e}")
        return 1


if __name__ == '__main__':
    sys.exit(main())