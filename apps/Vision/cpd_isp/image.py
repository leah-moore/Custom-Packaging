import cv2
import numpy as np
from cv2 import aruco

class CorrectedImage:
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
        p_tr = id_to_corner[0][0][0]  # top right
        p_tl = id_to_corner[1][0][0]  # top left
        p_bl = id_to_corner[2][0][0]  # bottom left
        p_br = id_to_corner[3][0][0]  # bottom rightd

        self.raw_pts = np.array([p_tr, p_tl, p_bl, p_br], dtype=np.float32) # List of points
    
        width_top = np.linalg.norm(p_tr - p_tl)
        width_bottom = np.linalg.norm(p_br - p_bl)
        self.raw_width = int(max(width_top, width_bottom))
        
        height_left = np.linalg.norm(p_tl - p_bl)
        height_right = np.linalg.norm(p_tr - p_br)
        self.raw_height = int(max(height_left, height_right))

        self.corrected_image = None
        self.corrected_width = None
        self.corrected_height = None
        self.processed_image = None

    def perspectiveWarpResize(self, width, height):
        new_pts = np.array([
            [width, 0],        # top right
            [0, 0],            # top left
            [0, height],       # bottom left
            [width, height]   # bottom right
        ], dtype=np.float32)
    
        M = cv2.getPerspectiveTransform(self.raw_pts, new_pts)
        self.corrected_image = cv2.warpPerspective(self.image, M, (width, height))

        self.corrected_width = width
        self.corrected_height = height

    def perspectiveWarpResizeRaw(self):
        self.perspectiveWarpResize(self.raw_width, self.raw_height)

    def phaseCorrelationPreProcess(self, is_old, threshold=100):
        overlap_w = self.corrected_width // 2 # get aproximate width

        gray = cv2.cvtColor(self.corrected_image, cv2.COLOR_RGB2GRAY) # Convert to grayscale
        
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
        #thresh = self.high_pass(thresh)

        # CLAHE (Adaptive Histogram Equalization)
        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
        thresh = clahe.apply(thresh.astype(np.uint16))
        
        # Normalize Image
        # thresh = self.normalize(thresh)

        # Apply Hann Window
        thresh = self.apply_horizontal_window(thresh)

        self.processed_image = thresh

    def resizeImage(self, target_width, target_height):
        if target_height > self.corrected_height or target_width > self.corrected_width:
            raise ValueError("Target size must be <= original size")

        self.processed_resized_image = self.processed_image[0:target_height, 0:target_width]

    def process(self, target_width, target_height, is_old, threshold=110):
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


    def normalize(self, img):
        img = img.astype(np.float32)
        img = (img - img.mean()) / (img.std() + 1e-6)
        return img.astype(np.uint16)


    def high_pass(self, gray):
        blur = cv2.GaussianBlur(gray, (0,0), 30)
        return cv2.subtract(gray, blur)


class ArucoError(Exception):
    pass


class RequiredMarkersMissingError(ArucoError):
    def __init__(self, scanned_ids):
        self.scanned_ids = scanned_ids
        super().__init__(f"Ids required are [0, 1, 2, 3]; Ids scanned: {scanned_ids}")
