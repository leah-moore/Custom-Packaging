import cv2
import numpy as np
from cv2 import aruco

class ImagePair:
    def __init__(self, image_a, image_b):
        self.image_a = RawImage(image_a)
        self.image_b = RawImage(image_b)
        
        # Ensure the images are the same size
        self.height = min(self.image_a.height, self.image_b.height)
        self.width = min(self.image_a.width, self.image_b.width)

        self.image_a.resizeImage(self.width, self.height)
        self.image_b.resizeImage(self.width, self.height)

        self.blend_images()

    def blend_images(self, blend_start=0.49, blend_end=0.51):
        mask = self.create_gradient_mask(blend_start, blend_end)

        # Expand mask to 3 channels to work with colour images
        mask_3ch = np.stack([mask, mask, mask], axis=2)

        # Blend: where mask=1 use A, where mask=0 use B
        img_a_f = self.image_a.corrected_image.astype(np.float32)
        img_b_f = self.image_b.corrected_image.astype(np.float32)

        self.image = (img_a_f * mask_3ch) + (img_b_f * (1.0 - mask_3ch))

    def create_gradient_mask(self, blend_start, blend_end):
        mask = np.zeros((self.height, self.width), dtype=np.float32)

        start_px = int(self.height * blend_start)
        end_px   = int(self.height * blend_end)

        # Top section — fully Image A
        mask[:start_px, :] = 1.0

        # Gradient section — smooth blend from A to B
        gradient = np.linspace(1.0, 0.0, end_px - start_px, dtype=np.float32)
        mask[start_px:end_px, :] = gradient[:, np.newaxis]  # broadcast across width

        # Bottom section — fully Image B
        mask[end_px:, :] = 0.0

        return mask

    def phaseCorrelationPreProcess(self, is_old, threshold=30):
        overlap_w = self.width // 2 # get aproximate width

        gray = cv2.cvtColor(self.image, cv2.COLOR_RGB2GRAY) # Convert to grayscale
        
        # Select ROI
        if not is_old:
            roi = gray[:, -overlap_w:]
        else:
            roi = gray[:, :overlap_w]

        # Apply Threshold to reject background
        edge_mask = roi > threshold
        thresh = roi * edge_mask

        # Image processing
        # High Pass Filter
        # thresh = self.high_pass(thresh)

        # CLAHE (Adaptive Histogram Equalization)
        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
        thresh = clahe.apply(thresh.astype(np.uint8))
        #thresh = (thresh / 65535).astype(np.float32)
        
        # Normalize Image
        #thresh = self.normalize(thresh)

        # Apply Hann Window
        thresh = self.apply_horizontal_window(thresh)

        self.processed_image = thresh
    
    def resizeImage(self, target_width, target_height):
        if target_height > self.height or target_width > self.width:
            raise ValueError("Target size must be <= original size")

        self.processed_resized_image = self.processed_image[0:target_height, 0:target_width]
    
    def process(self, target_width, target_height, is_old, threshold=30):
        self.phaseCorrelationPreProcess(is_old, threshold)
        self.resizeImage(target_width, target_height)
    
    def tukey_1d(self, n, alpha=0.4):
        x = np.linspace(0, 1, n)
        w = np.ones(n)
    
        first = alpha / 2
        last = 1 - alpha / 2
    
        # left taper
        mask = x < first
        w[mask] = 0.5 * (1 + np.cos(np.pi * ((2*x[mask]/alpha) - 1)))
    
        # right taper
        mask = x > last
        w[mask] = 0.5 * (1 + np.cos(np.pi * ((2*x[mask]/alpha) - (2/alpha) + 1)))
    
        return w

    def apply_horizontal_window(self, patch, alpha=0.4):
        h, w = patch.shape
        win_x = self.tukey_1d(w, alpha)
    
        # broadcast vertically (no y windowing)
        window = np.tile(win_x, (h, 1))
    
        return patch * window

 
class RawImage:
    def __init__(self, image):
        self.image = image

        # set up ArUco Scanner in Open CV
        aruco_dict = aruco.getPredefinedDictionary(aruco.DICT_4X4_50)
        aruco_params = aruco.DetectorParameters()
        detector = aruco.ArucoDetector(aruco_dict, aruco_params)

        # detect markers in image
        self.corners, self.ids, _ = detector.detectMarkers(self.image)

        # Sort them corners by ID assuming IDs 0–3 are top-right, top-left, bottom-left, bottom-right
        id_to_corner = {int(id_): c for id_, c in zip(self.ids.flatten(), self.corners)}
        
        # Ensure that the expected ones are there
        required_ids = [0, 1, 2, 3]
        if not all(i in id_to_corner for i in required_ids):
            raise RequiredMarkersMissingError(id_to_corner.keys())

        # Sort markers and extract points
        p_tr = id_to_corner[1][0][0]  # top right
        p_tl = id_to_corner[2][0][0]  # top left
        p_bl = id_to_corner[3][0][0]  # bottom left
        p_br = id_to_corner[0][0][0]  # bottom rightd

        # Calculate Dimensions
        self.raw_pts = np.array([p_tr, p_tl, p_bl, p_br], dtype=np.float32) # List of points
    
        width_top = np.linalg.norm(p_tr - p_tl)
        width_bottom = np.linalg.norm(p_br - p_bl)
        self.width = int(max(width_top, width_bottom))
        
        height_left = np.linalg.norm(p_tl - p_bl)
        height_right = np.linalg.norm(p_tr - p_br)
        self.height = int(max(height_left, height_right))

        # Perspective Transform
        new_pts = np.array([
            [self.width, 0],        # top right
            [0, 0],            # top left
            [0, self.height],       # bottom left
            [self.width, self.height]   # bottom right
        ], dtype=np.float32)
    
        M = cv2.getPerspectiveTransform(self.raw_pts, new_pts)
        self.corrected_image = cv2.warpPerspective(self.image, M, (self.width, self.height))
    
    def resizeImage(self, w, h):
        if h > self.height or w > self.width:
            raise ValueError("Target size must be <= original size")

        self.corrected_image = self.corrected_image[0:h, 0:w]



class ArucoError(Exception):
    pass


class RequiredMarkersMissingError(ArucoError):
    def __init__(self, scanned_ids):
        self.scanned_ids = scanned_ids
        super().__init__(f"Ids required are [0, 1, 2, 3]; Ids scanned: {scanned_ids}")
