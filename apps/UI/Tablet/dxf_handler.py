"""
DXF Handler Module
Reads, parses, and manipulates DXF files for die-line placement and visualization.
"""

from __future__ import annotations
from typing import List, Tuple, Optional, Dict
from pathlib import Path
import numpy as np

try:
    import ezdxf
    HAS_EZDXF = True
except ImportError:
    HAS_EZDXF = False

from shapely.geometry import Polygon, LineString, MultiLineString, Point, MultiPolygon, GeometryCollection
from shapely.ops import unary_union
from shapely.affinity import translate, rotate, scale


class DXFDieline:
    """Represents a die-line from a DXF file with transformation capabilities"""
    
    def __init__(self, filepath: Path):
        self.filepath = Path(filepath)
        self.geometries = []  # List of Shapely geometries
        self.bounds = None
        self.metadata = {}
        self.transformations = {
            'translate_x': 0.0,
            'translate_y': 0.0,
            'rotate_degrees': 0.0,
            'scale_x': 1.0,
            'scale_y': 1.0,
        }
        
        if HAS_EZDXF:
            self._load_from_dxf(filepath)
        else:
            self._load_from_dxf_fallback(filepath)
    
    def _load_from_dxf(self, filepath: Path) -> None:
        """Load DXF using ezdxf library"""
        try:
            doc = ezdxf.readfile(str(filepath))
            msp = doc.modelspace()
            
            # Extract geometries from entities
            for entity in msp.query('*'):
                geom = self._entity_to_geometry(entity)
                if geom is not None and not geom.is_empty:
                    self.geometries.append(geom)
            
            if self.geometries:
                combined = unary_union(self.geometries)
                self.bounds = combined.bounds
                self.metadata['entity_count'] = len(self.geometries)
                self.metadata['source'] = 'ezdxf'
        
        except Exception as e:
            raise ValueError(f"Failed to load DXF file: {e}")
    
    def _load_from_dxf_fallback(self, filepath: Path) -> None:
        """Fallback parser for basic DXF support without ezdxf"""
        try:
            lines = []
            with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()
            
            # Very basic DXF parsing - extract LINE and LWPOLYLINE entities
            # This is a simplified approach; ezdxf is strongly recommended
            sections = content.split('SECTION')
            for section in sections:
                if 'ENTITIES' in section:
                    # Extract LWPOLYLINE and LINE segments
                    entities = section.split('LWPOLYLINE') + section.split('LINE')
                    for ent in entities:
                        if '10' in ent:  # Start of coordinates
                            # This is highly simplified; real parsing is complex
                            pass
            
            self.metadata['source'] = 'fallback_parser'
            self.metadata['warning'] = 'Fallback parser: install ezdxf for full support'
        
        except Exception as e:
            raise ValueError(f"Failed to parse DXF file with fallback: {e}")
    
    def _entity_to_geometry(self, entity) -> Optional: # type: ignore
        """Convert ezdxf entity to Shapely geometry"""
        try:
            if entity.dxftype() == 'LINE':
                start = entity.dxf.start
                end = entity.dxf.end
                return LineString([(start[0], start[1]), (end[0], end[1])])
            
            elif entity.dxftype() == 'LWPOLYLINE':
                points = [(pt[0], pt[1]) for pt in entity.get_points()]
                if len(points) >= 2:
                    if entity.close:
                        return Polygon(points)
                    else:
                        return LineString(points)
            
            elif entity.dxftype() == 'POLYLINE':
                points = [(pt[0], pt[1]) for pt in entity.get_points()]
                if len(points) >= 2:
                    if entity.dxf.flags & 1:  # Closed flag
                        return Polygon(points)
                    else:
                        return LineString(points)
            
            elif entity.dxftype() == 'CIRCLE':
                center = entity.dxf.center
                radius = entity.dxf.radius
                return Point(center[0], center[1]).buffer(radius)
            
            elif entity.dxftype() == 'ARC':
                center = entity.dxf.center
                radius = entity.dxf.radius
                start_angle = entity.dxf.start_angle
                end_angle = entity.dxf.end_angle
                # Approximate arc as circle for now
                return Point(center[0], center[1]).buffer(radius)
            
            elif entity.dxftype() == 'HATCH':
                # Extract boundary paths
                boundaries = []
                for path in entity.paths:
                    if path.path_type_flags & 1:  # Polyline path
                        points = [(pt[0], pt[1]) for pt in path.vertices]
                        if len(points) >= 3:
                            boundaries.append(Polygon(points))
                if boundaries:
                    return unary_union(boundaries)
            
        except Exception:
            pass
        
        return None
    
    def translate(self, dx: float, dy: float) -> None:
        """Translate geometries"""
        self.transformations['translate_x'] += dx
        self.transformations['translate_y'] += dy
    
    def rotate(self, degrees: float, origin: Tuple[float, float] = (0, 0)) -> None:
        """Rotate geometries"""
        self.transformations['rotate_degrees'] += degrees
    
    def scale_geom(self, sx: float, sy: float, origin: Tuple[float, float] = (0, 0)) -> None:
        """Scale geometries"""
        self.transformations['scale_x'] *= sx
        self.transformations['scale_y'] *= sy
    
    def reset_transform(self) -> None:
        """Reset all transformations"""
        self.transformations = {
            'translate_x': 0.0,
            'translate_y': 0.0,
            'rotate_degrees': 0.0,
            'scale_x': 1.0,
            'scale_y': 1.0,
        }
    
    def get_transformed_geometries(self) -> List:
        """Apply all transformations and return modified geometries"""
        transformed = []
        
        for geom in self.geometries:
            # Apply scale
            sx = self.transformations['scale_x']
            sy = self.transformations['scale_y']
            if sx != 1.0 or sy != 1.0:
                geom = scale(geom, xfact=sx, yfact=sy, origin=(0, 0))
            
            # Apply rotation
            if self.transformations['rotate_degrees'] != 0.0:
                geom = rotate(geom, self.transformations['rotate_degrees'], origin=(0, 0))
            
            # Apply translation
            dx = self.transformations['translate_x']
            dy = self.transformations['translate_y']
            if dx != 0.0 or dy != 0.0:
                geom = translate(geom, xoff=dx, yoff=dy)
            
            transformed.append(geom)
        
        return transformed
    
    def get_combined_geometry(self):
        """Get all geometries combined into single geometry"""
        transformed = self.get_transformed_geometries()
        if transformed:
            return unary_union(transformed)
        return None
    
    def get_bounds(self) -> Optional[Tuple[float, float, float, float]]:
        """Get bounds of transformed geometries"""
        geom = self.get_combined_geometry()
        if geom and not geom.is_empty:
            return geom.bounds
        return None
    
    def get_info(self) -> Dict:
        """Get metadata and info about the DXF"""
        bounds = self.get_bounds()
        return {
            'filepath': str(self.filepath),
            'entity_count': len(self.geometries),
            'bounds': bounds,
            'bounds_width': bounds[2] - bounds[0] if bounds else None,
            'bounds_height': bounds[3] - bounds[1] if bounds else None,
            'transformations': self.transformations,
            'metadata': self.metadata,
        }


class VisionDXFAligner:
    """Automatic registration of DXF die-lines to vision output"""
    
    @staticmethod
    def auto_register(vision_image_path: Path, dxf_dieline: DXFDieline) -> Dict:
        """
        Attempt automatic registration of DXF to vision image.
        
        Returns transform parameters:
        {
            'translate_x': float,
            'translate_y': float,
            'rotate_degrees': float,
            'scale_factor': float,
            'confidence': float (0-1),
        }
        
        NOTE: Requires OpenCV and advanced feature matching.
        For now, returns placeholder with instructions.
        """
        
        # TODO: Implement using:
        # - OpenCV feature detection (SIFT, AKAZE, ORB)
        # - Vision image → edge detection → contour matching
        # - DXF contours vs vision contours → optimization
        # - Or use manual fiducial markers if available
        
        return {
            'translate_x': 0.0,
            'translate_y': 0.0,
            'rotate_degrees': 0.0,
            'scale_factor': 1.0,
            'confidence': 0.0,
            'note': 'Auto-registration not yet implemented. Use manual placement.',
        }
    
    @staticmethod
    def manual_placement_ui_hints() -> str:
        """Provide hints for manual DXF placement in UI"""
        return """
MANUAL DIE-LINE PLACEMENT GUIDE:
1. Load vision image (stitched cardboard feed)
2. Load DXF die-lines (from computer vision output)
3. Adjust in the UI:
   - Drag to reposition
   - Rotate using slider or input
   - Scale if needed for registration
4. Visual feedback shows overlap/alignment
5. Once aligned, send to gantry system
        """


# Helper functions for DXF manipulation in batches

def load_multiple_dxfs(folder_path: Path) -> Dict[str, DXFDieline]:
    """Load all DXF files from a folder"""
    dxfs = {}
    for dxf_file in folder_path.glob('*.dxf'):
        try:
            dxfs[dxf_file.stem] = DXFDieline(dxf_file)
        except Exception as e:
            print(f"Failed to load {dxf_file}: {e}")
    return dxfs


def export_transformed_dxf(dieline: DXFDieline, output_path: Path) -> bool:
    """Export transformed DXF to file (requires ezdxf)"""
    if not HAS_EZDXF:
        print("ERROR: ezdxf required for DXF export. Install with: pip install ezdxf")
        return False
    
    try:
        doc = ezdxf.new()
        msp = doc.modelspace()
        
        # Get transformed geometries
        transformed = dieline.get_transformed_geometries()
        
        for geom in transformed:
            _add_shapely_to_dxf(msp, geom)
        
        doc.saveas(str(output_path))
        return True
    
    except Exception as e:
        print(f"Failed to export DXF: {e}")
        return False


def _add_shapely_to_dxf(msp, geom) -> None:
    """Add Shapely geometry to DXF modelspace"""
    if not HAS_EZDXF:
        return
    
    try:
        geom_type = geom.geom_type
        
        if geom_type == 'LineString':
            coords = list(geom.coords)
            msp.add_lwpolyline2d(coords)
        
        elif geom_type == 'LinearRing' or geom_type == 'Polygon':
            if geom_type == 'Polygon':
                coords = list(geom.exterior.coords)
            else:
                coords = list(geom.coords)
            msp.add_lwpolyline2d(coords, dxfattribs={'flags': 1})  # Closed
        
        elif geom_type == 'MultiLineString':
            for line in geom.geoms:
                _add_shapely_to_dxf(msp, line)
        
        elif geom_type == 'MultiPolygon':
            for poly in geom.geoms:
                _add_shapely_to_dxf(msp, poly)
        
        elif geom_type == 'GeometryCollection':
            for part in geom.geoms:
                _add_shapely_to_dxf(msp, part)
    
    except Exception as e:
        print(f"Warning: Could not add geometry to DXF: {e}")
