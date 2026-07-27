import { api } from "./api";

// export const getBucketStructure = async () => {
//   try {
//     const response = await api.get("/api/v1/blob");
//     return response.data;
//   } catch (error) {
//     console.error("Error fetching bucket structure:", error);
//     throw error;
//   }
// };

// export const syncBucketStructure = async () => {
//   try {
//     const response = await api.post("/api/v1/blob/sync");
//     return response.data;
//   } catch (error) {
//     console.error("Error syncing bucket structure:", error);
//     throw error;
//   }
// };

// export const uploadFile = async (file, file_path, onUploadProgress) => {
//   try {
//     const formData = new FormData();
//     formData.append("file", file);

//     const response = await api.post("/api/v1/blob/upload", formData, {
//       headers: {
//         "Content-Type": "multipart/form-data",
//       },
//       onUploadProgress,
//       params: {
//         file_path,
//       },
//     });

//     return response.data;
//   } catch (error) {
//     console.error("Error uploading file:", error);
//     throw error;
//   }
// };

// export const deleteFile = async (file_path) => {
//   try {
//     const response = await api.delete("/api/v1/blob/delete", {
//       params: {
//         file_path: file_path,
//       },
//     });
//     return response.data;
//   } catch (error) {
//     console.error("Error deleting file:", error);
//     throw error;
//   }
// };

// export const bulkDeleteFiles = async (folder_path) => {
//   try {
//     console.log("Initiating bulk delete for folder path:", String(folder_path));
//     const response = await api.delete("/api/v1/blob/bulk-delete", {
//       params: {
//         folder_path: folder_path,
//       },
//     });
//     return response.data;
//   } catch (error) {
//     console.error("Error bulk deleting files:", error);
//     throw error;
//   }
// };

// export const getUserFiles = async () => {
//   try {
//     const response = await api.get("/api/v1/files");
//     return response.data;
//   } catch (error) {
//     console.error("Error fetching user files:", error);
//     throw error;
//   }
// };