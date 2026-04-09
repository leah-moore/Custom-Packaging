import cv2
import numpy as np
from .raw_image import ImagePair

class ImageStitcher:
    def __init__(self, initial_image:ImagePair, margin=150.0, blend_width=10):
        self.dx = None
        self.dy = None
        self.margin = margin
        self.blend_width = blend_width  # Width of the blending region in pixels

        h = initial_image.height
        w = initial_image.width

        self.canvas = np.zeros((h + 2 * int(self.margin), 
                                w + 2 * int(self.margin), 3), dtype=np.uint8)
        # Initial global zero
        self.gx = self.margin
        self.gy = self.margin
        self.canvas[int(self.gy):int(self.gy)+h, int(self.gx):int(self.gx)+w] = initial_image.image
        self.images = [initial_image]
    
    def add_image(self, image:ImagePair):
        self.images.append(image)

        h_curr, w_curr = self.images[-1].image.shape[:2]
        h_prev, w_prev = self.images[-2].image.shape[:2]

        h = min(h_curr, h_prev)
        w = min(w_curr, w_prev)//2
        
        self.images[-1].process(w, h, False) # Flip these based on the direction feeding in
        self.images[-2].process(w, h, True)
        self.estimate_translation(self.images[-2], self.images[-1])

        self.dx += w_curr/2.0 # Also flip this

        if self.dx < 0:
            self.canvas = np.pad(self.canvas, ((0, 0), (0, abs(int(self.dx))), (0, 0)), constant_values=0)
            self.gx -= self.dx
            self.gy -= self.dy
        else:
            self.canvas = np.pad(self.canvas, ((0, 0), (abs(int(self.dx)), 0), (0, 0)), constant_values=0)
            self.gy -= self.dy

        print(f"dx: {self.dx}, dy: {self.dy}")
        
        self._place_image_subpixel_with_blend(self.images[-1].image, self.gx, self.gy)

        return self.dx, self.dy
    
    def estimate_translation(self, prev, curr):
     
        (dx, dy), confidence = cv2.phaseCorrelate(
            prev.processed_resized_image.astype(np.float32),
            curr.processed_resized_image.astype(np.float32)
        )

        if confidence < 0.1:  # Adjust threshold based on your data
            print(f"Warning: Low confidence {confidence}, shift might be unreliable")
        else:
            print(f"Confidence: {confidence}")
        
        if abs(dx) > curr.width/2.0:
            dx = curr.width - abs(dx)
        
        if abs(dy) > curr.height/2.0:
            dy = curr.height - abs(dy)
        
        self.dx = dx
        self.dy = dy
    
    def _place_image_subpixel_with_blend(self, image, x, y):
        h, w = image.shape[:2]
        
        # Create translation matrix with sub-pixel shifts
        x_int = int(np.floor(x))
        y_int = int(np.floor(y))
        
        dx_subpixel = x - x_int
        dy_subpixel = y - y_int
        
        # Translation matrix
        M = np.array([[1, 0, dx_subpixel],
                        [0, 1, dy_subpixel]], dtype=np.float32)
        
        # Warp image with sub-pixel shift
        shifted_image = cv2.warpAffine(
            image, 
            M, 
            (w, h),
            flags=cv2.INTER_CUBIC,
            borderMode=cv2.BORDER_CONSTANT,
            borderValue=0
        )
        
        # Extract the region where the new image will be placed
        canvas_region = self.canvas[y_int:y_int+h, x_int:x_int+w].copy()
        
        # Create masks for blending
        canvas_mask = (np.sum(canvas_region, axis=2) > 0).astype(np.float32)
        image_mask = (np.sum(shifted_image, axis=2) > 0).astype(np.float32)
        
        # Find overlap region
        overlap_mask = canvas_mask * image_mask
        
        # Create alpha blend mask for the overlap region
        alpha_new = np.ones_like(image_mask)
        
        if np.any(overlap_mask > 0):
            overlap_indices = np.where(overlap_mask > 0)
            
            if len(overlap_indices[0]) > 0:
                # Determine blend direction by checking WHERE in the image the overlap occurs
                # Find the horizontal center of the overlap
                overlap_cols = overlap_indices[1]
                overlap_center_col = np.mean(overlap_cols)
                image_center_col = w / 2.0
                
                # If overlap is on the LEFT side of the new image → new image is on the RIGHT
                # If overlap is on the RIGHT side of the new image → new image is on the LEFT
                blend_left_to_right = overlap_center_col < image_center_col
                
                for row in range(h):
                    cols_in_overlap = overlap_indices[1][overlap_indices[0] == row]
                    if len(cols_in_overlap) > 0:
                        left_edge = cols_in_overlap.min()
                        right_edge = cols_in_overlap.max()
                        overlap_width = right_edge - left_edge + 1
                        
                        actual_blend_width = min(self.blend_width, overlap_width)
                        
                        if blend_left_to_right:
                            # Overlap on left side of new image → blend from old to new (left to right)
                            for col in range(left_edge, min(left_edge + actual_blend_width, right_edge + 1)):
                                alpha_new[row, col] = (col - left_edge) / actual_blend_width
                        else:
                            # Overlap on right side of new image → blend from new to old (right to left)
                            for col in range(max(right_edge - actual_blend_width + 1, left_edge), right_edge + 1):
                                alpha_new[row, col] = (right_edge - col) / actual_blend_width
        
        # Expand alpha to 3 channels
        alpha_new_3ch = np.stack([alpha_new] * 3, axis=2)
        alpha_old_3ch = 1.0 - alpha_new_3ch
        
        # Blend the images
        blended_region = (shifted_image.astype(np.float32) * alpha_new_3ch + 
                         canvas_region.astype(np.float32) * alpha_old_3ch)
        
        # Where there's no overlap, use the original images
        no_overlap = (overlap_mask == 0)
        no_overlap_3ch = np.stack([no_overlap] * 3, axis=2)
        
        # Combine: use new image where only new exists, old where only old exists, blend where both exist
        result = np.where(no_overlap_3ch & (image_mask[:, :, np.newaxis] > 0), 
                         shifted_image,
                         np.where(no_overlap_3ch & (canvas_mask[:, :, np.newaxis] > 0),
                                 canvas_region,
                                 blended_region))
        
        # Place the blended result on the canvas
        self.canvas[y_int:y_int+h, x_int:x_int+w] = result.astype(np.uint8)
    
    def _place_image_subpixel(self, image, x, y):
        """Original method kept for reference - not used anymore"""
        h, w = image.shape[:2]
        
        x_int = int(np.floor(x))
        y_int = int(np.floor(y))
        
        dx_subpixel = x - x_int
        dy_subpixel = y - y_int
        
        M = np.float32([[1, 0, dx_subpixel],
                        [0, 1, dy_subpixel]])
        
        shifted_image = cv2.warpAffine(
            image, 
            M, 
            (w, h),
            flags=cv2.INTER_CUBIC,
            borderMode=cv2.BORDER_CONSTANT,
            borderValue=0
        )
        
        self.canvas[y_int:y_int+h, x_int:x_int+w] = shifted_image



